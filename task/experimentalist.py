from collections import OrderedDict
from datetime import date
from multiprocessing import Queue, Value, Event
from threading import Timer
from time import time
import json
from os import path
import numpy as np
from PyQt5 import QtCore

from data_management.database import Database
from task.ressources import GripManager, ValveManager, GripTracker, SoundManager
from task.stimuli_finder import StimuliFinder
from utils.utils import log


class Experimentalist(QtCore.QThread, QtCore.QObject):

    trigger = QtCore.pyqtSignal()

    def __init__(self, game_window, interface_window, graphic_queue):

        super(Experimentalist, self).__init__()

        self.game_window = game_window
        self.interface_window = interface_window

        self.graphic_queue = graphic_queue

        self.grip_queue = Queue()
        self.grip_value = Value('i', 0)

        self.grip_tracker = GripTracker(
            change_queue=self.grip_queue
        )

        # --------- PROCESS FOR GRIP AND VALVE --- #

        # Get IP address of the RPi
        parameters_folder = path.abspath("{}/../parameters".format(path.dirname(path.abspath(__file__))))
        with open("{}/raspberry_pi.json".format(parameters_folder)) as file:
            rpi_ip_address = json.load(file)["ip_address"]

        self.grip_manager = GripManager(
            grip_value=self.grip_value, grip_queue=self.grip_queue, rpi_ip_address=rpi_ip_address)

        self.valve_manager = ValveManager(rpi_ip_address=rpi_ip_address)

        # -------- SOUND --------- #

        self.sound_manager = SoundManager(n_sound_thread=8)

        # -------- PARAMETERS --------- #

        self.parameters = None

        self.task_running = False

        # ------- STIMULI FINDER ------- #

        self.stimuli_finder = StimuliFinder()

        # ------- FOR FUTURE SAVING ---- #
        self.choice = None

        self.gauge_level = 0

        self.stimuli_parameters = {}
        self.to_save = []
        self.error = None

        self.dice_output = 0

        self.current_saving = Event()
        self.data_saved = Event()

        # -------- TIME & TIMERS ----------- #

        self.timer = None
        self.animation_timers = []

        self.time_to_decide = -1
        self.time_to_come_back_to_the_grip = -1
        self.inter_trial_time = -1
        self.fixation_time = -1

        # ------- TRIAL COUNTERS ------ #

        self.trial_counter = [0, 0]

        self.n_trial_inside_block = 0

        self.n_block = 0

        # ------ INIT ------ #

        self.initialize()

# ------------------------ INIT ------------------------------------- #

    def initialize(self):

        self.grip_tracker.start()
        self.sound_manager.start()

    def run(self):

        log("Experimentalist: Run.")
        # Show graphic interface
        self.command(self.interface_window.show)

        self.wait_for_graphic_msg()

# ----------------------------- GET EVENTS FROM GRAPHIC INTERFACE ----------------------------------------------- #

    def wait_for_graphic_msg(self):

        log("Experimentalist: Wait for graphic msg.")

        graphic_msg = self.graphic_queue.get()

        if graphic_msg[0] == "game_close_window":

            log("Experimentalist: Game close window.")
            self.end_game()

        elif graphic_msg[0] == "interface_close_task":

            log("Experimentalist: Interface close task.")
            self.end_game()

        elif graphic_msg[0] == "interface_close_window":

            log("Experimentalist: Interface close window.")
            self.end_program()
            return

        elif graphic_msg[0] == "interface_run":

            log("Experimentalist: Interface run.")
            # Get parameters from graphic interface
            self.parameters = graphic_msg[1]

            self.prepare_game()

        elif graphic_msg[0] == "game_play":

            log("Experimentalist: Game play.")
            self.play_game()

        elif graphic_msg[0] == "game_left":

            log("Experimentalist: choice left.")
            self.decide("left")

        elif graphic_msg[0] == "game_right":

            log("Experimentalist: choice right.")
            self.decide("right")

        else:
            log("ERROR: msg from graphics not understood.")

        self.wait_for_graphic_msg()

# ------------------------------------------- TOOLS ---------------------------------------------------------- #

    def command(self, function):

        self.trigger.connect(function)
        self.trigger.emit()

# --------------------------------------- END PROGRAM ------------------------------------------------------------ #

    def end_program(self):

        log("Experimentalist: end_program")

        if self.current_saving.is_set():
            self.data_saved.wait()

        if self.timer:
            self.timer.cancel()
        for timer in self.animation_timers:
            timer.cancel()

        self.grip_tracker.end()
        self.grip_manager.end()
        self.valve_manager.end()
        self.sound_manager.end()

        self.game_window.standalone = True
        self.command(self.game_window.close)
        self.command(self.interface_window.close)

# ------------------------------------ START AND END GAME ---------------------------------------------------------- #

    def prepare_game(self):

        # Show 'trial counter' on interface window
        self.command(self.interface_window.show_progression_bar)

        if self.parameters["fake"]:
            self.game_window.track_fake_grip(queue=self.grip_queue, value=self.grip_value)

        else:

            if not self.valve_manager.isRunning():
                self.valve_manager.establish_connection()
                self.valve_manager.start()

            if not self.grip_manager.isRunning():
                self.grip_manager.establish_connection()
                self.grip_manager.start()

        # Tell to stimuli generator parameters to use
        self.stimuli_finder.set_parameters(
            control_trials_proportion=self.parameters["control_trials_proportion"],
            with_losses_proportion=self.parameters["with_losses_proportion"],
            incongruent_proportion=self.parameters["incongruent_proportion"]
        )

        # Show 'pause screen' on game window
        self.game_window.current_step = "show_pause_screen"
        self.command(self.game_window.show)

        # Update display on graphic interface
        self.trial_counter = [0, 0]
        self.interface_window.trial_counter.set_trial_number(self.trial_counter)

        # Reinitialize
        self.to_save = []
        self.n_block = 0

        # Show 'trial counter' on interface window
        self.command(self.interface_window.show_trial_counter)

    def play_game(self):

        log('Experimentalist: PLAY GAME.')

        # Play appropriate sound
        self.sound_manager.play("start")

        # Begin a new block of trials
        self.begin_new_block()

    def end_game(self):

        log('Experimentalist: END GAME.')

        # Stop the grip tracker
        self.grip_tracker.cancel()

        # Stop all the timers
        if self.timer:
            self.timer.cancel()
        for timer in self.animation_timers:
            timer.cancel()

        # Update display on game window
        self.game_window.current_step = "hide"

        # Update display interface window
        self.command(self.interface_window.prepare_next_run)

        # Save the session (database)
        if self.parameters["save"]:

            self.save_session()

# ------------------------------------ START AND END BLOCK ---------------------------------------------------------- #

    def begin_new_block(self):

        log("Experimentalist: Start new block.")

        # Reinitialize
        self.n_trial_inside_block = 0
        self.gauge_level = self.parameters["initial_stock"]

        # Update display of game window
        self.game_window.set_gauge_color(color="black")
        self.game_window.set_gauge_quantity(quantity=self.gauge_level)

        # Launch new trial
        self.begin_new_trial()

    def end_block(self):

        log("Experimentalist: End of a block.")

        # Upgrade counter
        self.n_block += 1

        # After time for rewarding, launch new block
        reward_time = self.parameters["reward_time"] / 1000
        self.timer = Timer(reward_time, self.begin_new_block)
        self.timer.start()

        # Launch vending animation
        self.venting_gauge_animation()

# ------------------------------------ START AND END TRIAL ---------------------------------------------------------- #

    def begin_new_trial(self):

        log("Experimentalist: New trial.")

        # Reinitialize
        self.error = None
        self.time_to_decide = -1
        self.time_to_come_back_to_the_grip = -1
        self.inter_trial_time = -1
        self.fixation_time = -1

        # Update display on game window
        self.game_window.current_step = "show_gauge"

        # Prepare stimuli for future use
        self.set_stimuli_parameters()

        # Launch next step: wait for the user to grasp the grip
        self.wait_for_grasping()

    def end_trial(self):

        log("Experimentalist: End of trial.")

        # Save trial (on RAM)
        if self.parameters["save"] == 1:
            self.save_trial()

        # Update trial counters
        self.trial_counter[0] += 1
        if self.error is None:

            self.trial_counter[1] += 1  # One trial more without errors
            self.n_trial_inside_block += 1  # Increment the number of made trials inside the same block

        # Update display on graphic interface
        self.interface_window.trial_counter.set_trial_number(self.trial_counter)

        # If no error, continue
        if self.error is None:

            if self.n_trial_inside_block % self.parameters["trials_per_block"]:
                self.begin_new_trial()
            else:
                self.end_block()

        # Otherwise, begin a new block
        else:
            self.begin_new_block()

# ------------------------------------ SUB-STEPS OF TASK ---------------------------------------------------------- #

    def wait_for_grasping(self):

        # If user holds already the grip, go directly to next step
        if self.grip_value.value == 1:

            self.grasp_before_stimuli_display()

        # Otherwise wait for him to do it
        elif self.grip_value.value == 0:

            log("Experimentalist: wait for grasping.")

            self.grip_tracker.launch(
                handling_function=self.grasp_before_stimuli_display,
                msg="Go signal from wait_for_grasping")

        else:
            raise Exception("Something's wrong with the GripManager.")

    def grasp_before_stimuli_display(self):

        log("Experimentalist: grasp before stimuli display.")

        # Observe if the user holds the grip for a certain time, otherwise do what is appropriate
        self.grip_tracker.launch(
            handling_function=self.release_before_end_of_fixation_time,
            msg="go signal from grasp before stimuli display")

        # Launch a new timer: if user holds the grip, show the stimuli
        self.fixation_time = np.random.randint(
            self.parameters["fixation_time"][0], self.parameters["fixation_time"][1]) / 1000
        self.timer = Timer(self.fixation_time, self.show_stimuli)
        self.timer.start()

    def show_stimuli(self):

        log("Experimentalist: Show stimuli.")

        # Stop grip tracker whose purpose was to rise an error if user has release the grip
        self.grip_tracker.cancel()

        # Update display on game window
        self.game_window.current_step = "show_stimuli"

        # Launch new timer: after maximum time to decide, if no action took place, do what is appropriated.
        max_decision_time = self.parameters["max_decision_time"] / 1000
        self.timer = Timer(max_decision_time, self.did_not_take_decision)
        self.timer.start()

        # For future measure of time for choosing
        self.time_to_decide = time()

    def decide(self, choice):

        log("Experimentalist: Decide.")

        # Stop previous timer
        self.timer.cancel()

        # Measure time to decide
        self.time_to_decide = int((time() - self.time_to_decide) * 1000)

        # Play appropriated sound
        self.sound_manager.play("choice")

        # Save choice
        self.choice = choice

        # Update display on game window
        self.game_window.set_choice(choice=self.choice)
        self.game_window.current_step = "show_choice"

        # Launch new timer: limit for coming back to the grip
        max_return_time = self.parameters["max_return_time"] / 1000
        self.timer = Timer(max_return_time, self.did_not_came_back_to_the_grip)
        self.timer.start()

        # Launch grip detector: If grip state change, results will be displayed
        self.grip_tracker.launch(handling_function=self.show_results, msg="Add results if grip touched")

        # For future measure of time for coming back to the grip
        self.time_to_come_back_to_the_grip = time()

    def show_results(self):

        log("Experimentalist: Show results.")

        # Stop previous timer
        self.timer.cancel()

        # Measure time for coming back to the grip
        self.time_to_come_back_to_the_grip = int((time() - self.time_to_come_back_to_the_grip) * 1000)

        # Prepare results
        self.set_results()

        # Update display on game window
        self.game_window.current_step = "show_results"
        self.game_window.set_choice(choice=self.choice)

        # Launch new timer: after time for displaying results, launch inter-trial
        results_display_time = self.parameters["result_display_time"] / 1000
        self.timer = Timer(results_display_time, self.inter_trial)
        self.timer.start()

        # Start animation for filling up the gauge
        self.filling_gauge_animation()

    def inter_trial(self):

        log("Experimentalist: Inter-trial.")

        # Update display on game window
        self.game_window.current_step = "show_gauge"

        # Launch new timer: after time for inter-trial, go to end of the trial
        self.inter_trial_time = np.random.randint(
            self.parameters["inter_trial_time"][0],
            self.parameters["inter_trial_time"][1])\
            / 1000
        self.timer = Timer(self.inter_trial_time, self.end_trial)
        self.timer.start()

# ----------------------------------------- ERRORS --------------------------------------------------------------- #

    def punish(self):

        log("Experimentalist: PUNISH.")

        # Play appropriated sound
        self.sound_manager.play("punishment")

        # Update display on game window
        self.game_window.current_step = "show_black_screen"

        # After punishment time, go to end of trial
        punishment_time = self.parameters["punishment_time"] / 1000
        self.timer = Timer(punishment_time, self.end_trial)
        self.timer.start()

    def release_before_end_of_fixation_time(self):

        log("Experimentalist: Release grip before the end of the fixation time.")
        self.timer.cancel()

        self.error = "release before end of fixation time"
        self.punish()

    def did_not_take_decision(self):

        log("Experimentalist: Did not take a decision.")
        self.error = "too long to take a decision"
        self.time_to_decide = -1
        self.punish()

    def did_not_came_back_to_the_grip(self):

        log("Experimentalist: Did not came back to the grip.")
        self.time_to_come_back_to_the_grip = -1
        self.error = "did not came back to the grip"
        self.punish()

# ----------------------------------------- GAUGE ANIMATION ------------------------------------------------------ #

    def filling_gauge_animation(self):

        results_display_time = self.parameters["result_display_time"] / 1000

        reward = self.stimuli_parameters["{}_x{}".format(self.choice, self.dice_output)]

        # '+2' allows to have a short time before the beginning of the sequence and a short time at the end
        time_per_unity = results_display_time / (self.stimuli_finder.maximum_x + 2)

        if reward > 0:
            sound = "reward"
            sequence = np.arange(1, reward + 1)

        elif reward < 0:
            sound = "loss"
            sequence = np.arange(-1, reward - 1, -1)

        else:
            sequence = []
            sound = None

        self.animation_timers = []

        for i in sequence:
            timer = Timer(
                time_per_unity * np.absolute(i), self.set_gauge_quantity,
                kwargs={
                    "quantity": self.gauge_level + i,
                    "sound": sound
                }
            )
            timer.start()
            self.animation_timers.append(timer)

        self.gauge_level += reward

    def venting_gauge_animation(self):

        self.game_window.set_gauge_color(color="blue")

        reward_time = self.parameters["reward_time"] / 1000

        reward = self.gauge_level

        time_per_unity = reward_time / self.stimuli_finder.gauge_maximum

        if reward > 0:

            sequence = np.arange(1, reward + 1)

        else:
            sequence = []

        self.animation_timers = []

        for i in sequence:

            timer = Timer(
                time_per_unity * np.absolute(i), self.set_gauge_quantity,
                kwargs=
                {
                    "quantity": self.gauge_level - i,
                    "sound": "reward",
                    "water": True
                }
            )
            timer.start()
            self.animation_timers.append(timer)

    def set_gauge_quantity(self, **kwargs):

        self.game_window.set_gauge_quantity(quantity=kwargs["quantity"])
        self.sound_manager.play(sound=kwargs["sound"])
        if "water" in kwargs:
            if not self.parameters["fake"]:
                self.valve_manager.open(self.parameters["valve_opening_time"])
            else:
                log("FakeValveManager: GIVE WATER.")


# ----------------------------------------- STIMULI & RESULTS ---------------------------------------------------- #

    def set_stimuli_parameters(self):

        self.stimuli_parameters = self.stimuli_finder.find()

        self.game_window.set_parameters(self.stimuli_parameters)

    def set_results(self):

        p = self.stimuli_parameters["{}_p".format(self.choice)]
        r = np.random.random()
        self.dice_output = int(r > p)
        self.game_window.set_dice_output(self.dice_output)


# ------------------------------------- SAVE -------------------------------------------------------------------- #

    def save_trial(self):

        to_save = \
            {
                "error": self.error,
                "choice": self.choice,
                "dice_output": self.dice_output,
                "gauge_level": self.gauge_level,
                "n_trial_inside_block": self.n_trial_inside_block,
                "n_block": self.n_block,
                "time_to_decide": self.time_to_decide,
                "time_to_come_back_to_the_grip": self.time_to_come_back_to_the_grip,
                "inter_trial_time": int(self.inter_trial_time * 1000),
                "fixation_time": int(self.fixation_time * 1000)
            }
        to_save.update(self.stimuli_parameters)
        self.to_save.append(to_save)

    def save_session(self):

        # In case of trying to end program
        self.data_saved.clear()
        self.current_saving.set()

        log("Experimentalist: SAVE SESSION.")

        self.parameters.pop("save")

        if len(self.to_save) < 1:
            return

        database = Database()
        summary_table_name = "summary"

        # Verify if a summary table exists, otherwise, create it
        if not database.table_exists(summary_table_name):

            columns = OrderedDict()

            # Add columns for date and name of session table
            columns["date"] = str
            columns["session_table"] = str

            # Add a column for every parameter in parameter dic
            for key, value in sorted(self.parameters.items()):
                columns[key] = type(value)
            database.create_table(
                table_name=summary_table_name,
                columns=columns)

            log("Experimentalist: Summary table created.")

        else:
            log("Experimentalist: Summary table already exists.")

        # Create a session table
        log("Experimentalist: Create session table.")
        monkey = self.parameters["monkey"]
        session_table_name = "session_{}_{}".format(str(date.today()).replace("-", "_"), monkey)
        if database.table_exists(table_name=session_table_name):

            log("Experimentalist: Session table with name {} already exists.".format(session_table_name))

            idx = 2
            session_table_name += "({})".format(idx)
            while database.table_exists(table_name=session_table_name):
                log("Experimentalist: Session table with name {} already exists.".format(session_table_name))
                session_table_name = session_table_name.replace("({})".format(idx), "({})".format(idx+1))
                idx += 1

        columns = OrderedDict()
        for key, value in sorted(self.to_save[0].items()):
            columns[key] = type(value)

        database.create_table(
            table_name=session_table_name,
            columns=columns
        )

        log("Experimentalist: Session table created with name {}.".format(session_table_name))

        # Fill summary table
        database.fill_table(summary_table_name, **self.parameters, date=str(date.today()),
                            session_table=session_table_name)

        # Fill session table
        for i in range(len(self.to_save)):
            database.fill_table(session_table_name, **self.to_save[i])

        log("Experimentalist: DATA SAVED.")

        self.current_saving.clear()
        self.data_saved.set()





