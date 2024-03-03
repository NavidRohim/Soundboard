
import tkinter, tkmacosx, yaml, logging, os, dataclasses, pygame, pdb, tempfile, pyaudio, threading, wave, numpy
from pynput.keyboard._base import Key, KeyCode

from typing import Any, NoReturn, Callable, Mapping, Iterable, override
from tkinter import messagebox
from abc import ABC, abstractmethod

from tkinter import font as tkfont
from pygame._sdl2.audio import get_audio_device_names
    
from pynput.keyboard import HotKey, Listener

temp_directory = tempfile.gettempdir()
user_home_config = os.path.expanduser("~/.config")
program_config_home = f"{user_home_config}/soundboard"

media_path = "./media/"
sound_path = f"{program_config_home}/audio"
max_sounds_at_once = 5

# Check configuration exists
if not os.path.exists(user_home_config):
    os.mkdir(user_home_config)

if not os.path.exists(program_config_home):
    os.mkdir(program_config_home)

if not os.path.exists(sound_path):
    os.mkdir(sound_path)
        
# Setup logging
logger = logging.getLogger(__file__)
logger.setLevel(logging.DEBUG)
pygame.mixer.init()

file_handler = logging.FileHandler(f"{program_config_home}/dj_soundboard.log", mode="w+")
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')    
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
configuration_file = f"{program_config_home}/soundboard_config.yml"

class SoundboardError(Exception):
    pass

@dataclasses.dataclass
class SoundboardConfig:
    supported_formats: list[str]
    buttons_per_row: int
    default_volume: float
    default_font_size: int
    app_font: str

class AppResources:
    warning_image = "why.png"
    app_image = "512-mac.png"
    error_image = "bear.png"

# Global functions
def get_and_gen_yaml() -> dict[str, Any]:
    
    default_config = {
        "supported_formats": ["wav", "mp3", "ogg"], # Wav, ogg and mp3 only.
        "buttons_per_row": 5,
        "default_volume": 25,
        "default_font_size": 18,
        "app_font": "DINAlternate-Bold"
    }
    
    try:
        
        # Configuration file handling. Use `default_config` if the config file does not exist.
        def _generate_config() -> dict:
            with open(configuration_file, "w+") as write_config:
                # If it does not exist, create config and return default
                yaml.dump(default_config, write_config)
                logger.info("Using preset configuration.")
                return default_config
            
        if os.path.exists(configuration_file):
            with open(configuration_file, 'r') as yaml_config_file:
                yaml_config = yaml.safe_load(yaml_config_file)
                if yaml_config:
                    
                    # Check if yaml file is valid and has all keys
                    if not set(default_config).issubset(set(yaml_config)):
                        os.remove(configuration_file)
                        return get_and_gen_yaml()
                    
                    return yaml_config
                else:
                    # if the yaml file is empty, or cannot be read
                    return _generate_config()
        else:
            # If config file isn't found
            return _generate_config()
        
    except (PermissionError, FileNotFoundError):
        logger.error(f"Panik! cannot delete or cannot find config file. ({configuration_file}) returning default.")   
        return default_config

def rgb_to_hex(r: int, g: int, b: int):
    def _b10_to_hex_color(r: int, g: int, b: int) -> str:
        return f"#{hex(r)[2:]}{hex(g)[2:]}{hex(b)[2:]}"

    r = r if r <= 255 else 255
    r = g if g <= 255 else 255
    r = b if b <= 255 else 255
    return _b10_to_hex_color(r, g, b).upper().ljust(7, "0")

# Colors
default_color = rgb_to_hex(255, 255, 255) # White
default_highlight_color = rgb_to_hex(225, 225, 225) # Slightly darker white

# Other
try:
    config = SoundboardConfig(**get_and_gen_yaml())
    common_kwargs = {"sticky": "nsew", "pady": 2, "padx": 2}
    app_font = (config.app_font, config.default_font_size)
except TypeError:
    print("Outdated configuration.")
    exit(1)
    
class SoundboardABC(ABC):
    # Soundboard ABC. Basically just for type annotations
    
    def __init__(self) -> None:
        super().__init__()
        self._old_device: str | None = None
        self._playing_sounds: list[pygame.mixer.SoundType]  = []
        self._sb_buttons: list[SoundboardButton] = []

        self.recording_thread: SoundboardRecordingThread | None = None
        self.device_label = None
        self.after_id = None
        self.volume = config.default_volume
        self.input_devices: dict[int, str] = {}
        self.font: tkfont.Font
        
    @abstractmethod
    def change_iconphoto(self, default: bool, image: str) -> None:
        pass

    @abstractmethod
    def display_error(self, message: str) -> NoReturn: # type: ignore abc method
        pass
    
    @abstractmethod
    def display_warning(self, message: str) -> None:
        pass
    
    @abstractmethod
    def reload_sounds(self) -> None:
        pass
    
class SoundboardDecorators:
    
    @staticmethod
    def change_image_error(func: Callable) -> Callable:
        def _inner(self: SoundboardABC, *args, **kwargs) -> Any:
            self.change_iconphoto(False, AppResources.error_image)
            func_out = func(self, *args, **kwargs)
            self.change_iconphoto(False, AppResources.app_image)
            
            return func_out
        return _inner

    @staticmethod
    def change_image_warning(func: Callable) -> Callable:
        def _inner(self: SoundboardABC, *args, **kwargs) -> Any:
            self.change_iconphoto(False, AppResources.warning_image)
            func_out = func(self, *args, **kwargs)
            self.change_iconphoto(False, AppResources.app_image)
            
            return func_out
        return _inner

class SoundboardRecordingThread(threading.Thread):
    def __init__(self, master: SoundboardABC, input_device_index: int | None=None) -> None:
        super().__init__()
        
        self._stop_event = threading.Event()
        self.master = master
        self.audio: bytes = b''
        self.port_audio: pyaudio.PyAudio = pyaudio.PyAudio()
        self.hertz = 44100
        self.has_stopped = False
        self.device = input_device_index
        
    def stop(self):
        self._stop_event.set()
        self.has_stopped = True
        
    def run(self) -> None:
        
        try:
            rec_stream = self.port_audio.open(rate=self.hertz, channels=1, format=pyaudio.paInt16, frames_per_buffer=1024, input=True, input_device_index=self.device)
            frames = []
            while not self._stop_event.is_set():
                frames.append(rec_stream.read(1024))
            
            rec_stream.stop_stream()
            rec_stream.close()
            self.port_audio.terminate()
            
            mono_audio = b''.join(frames)
            mono_raw = numpy.frombuffer(mono_audio, dtype=numpy.int16)
            stereo_audio_np = numpy.repeat(mono_raw[:, numpy.newaxis], 2, axis=1)
            self.audio = stereo_audio_np.astype(numpy.int16).tobytes()
            
            if all(b == 0 for b in self.audio):
                self.master.display_warning("Audio is empty. Did you grant microphone permission from System Settings to this application?")
                
        except OSError as audio_error:
            logger.error(f"Audio error (Usually input): {audio_error}")
            self.master.display_warning("Was your selected microphone unplugged? Microphone no longer found.")
            self.master.reload_sounds()
            
    def write_to_file(self, file_name: str="recording.wav"):
        with wave.open(f"{sound_path}/{file_name}", 'wb') as wave_file:
            wave_file.setnchannels(2)
            wave_file.setsampwidth(self.port_audio.get_sample_size(pyaudio.paInt16))
            wave_file.setframerate(self.hertz)
            wave_file.writeframes(self.audio)

class SoundboardKeyboardListenerThread(Listener):
    def __init__(self, master: SoundboardABC) -> None:
        super().__init__(self.on_press, self.on_release)
        
        base_keypress = "<tab>"
        
        self.master = master
        self.hotkeys = [HotKey(HotKey.parse(f"{base_keypress}+{i}"), lambda index=i: self.master.play_sound(None, index - 1)) for i in range(1, 10)] # type: ignore
        self.hotkeys.extend([
            HotKey(HotKey.parse(f'{base_keypress}+r'), lambda: self.master.recording_action()), # type: ignore
            HotKey(HotKey.parse(f'{base_keypress}+p'), lambda: self.master.listen_to_playback()), # type: ignore
            HotKey(HotKey.parse(f'{base_keypress}+s'), lambda: self.master.write_playback_as_file()), # type: ignore
            HotKey(HotKey.parse(f'{base_keypress}+q'), lambda: self.master.stop_audio()), # type: ignore
            HotKey(HotKey.parse(f'{base_keypress}+0'), lambda: self.master.reload_sounds())
        ])
        
        self.start()
            
    def on_press(self, key):
        for hotkey in self.hotkeys: 
            hotkey.press(key)                                                                                                                                                                    
                                                                                                                                                                                            
    def on_release(self, key):                                                                                                                                                                         
        for hotkey in self.hotkeys:                                                                                                                                                            
            hotkey.release(key) 
            
class SoundboardButton(tkmacosx.Button, tkinter.Button): # NOTE: Inheriting from tkinter.Button so VSCode Intellisense functions correctly. It does not with tkmacos. tkinter.Button does not provide any functionality.
    
    def __init__(self, master: SoundboardABC, cnf=..., **kw):
        tkmacosx.Button.__init__(self, master, cnf, **kw)
        self.master_color = self._org_bg
        self.owner_master = master


        self.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            pady=50,
            font=master.font,
            highlightbackground=self.master_color,
            highlightcolor=self.master_color,
            border=2
        )
        
        self.bind("<Enter>", self.on_elem_enter)
        self.bind("<Leave>", self.on_elem_exit)
        self.bind("<Delete>", self.on_elem_press_del)
    
    def on_elem_enter(self, event: tkinter.Event) -> None:
        if not pygame.mixer.get_busy() and self.cget("background") == self.master_color:
            self["background"] = default_highlight_color
    
    def on_elem_exit(self, event: tkinter.Event) -> None:
        if not pygame.mixer.get_busy() and self.cget("background") == default_highlight_color:
            self["background"] = self.master_color

    def on_elem_press_del(self, event: tkinter.Event) -> None:
        try:
            os.remove(f"{sound_path}/{self["text"]}")
        except FileNotFoundError:
            pass
        
        self.owner_master.reload_sounds()
        
class SoundboardSystemButton(SoundboardButton):
    pass
        
class Soundboard(tkinter.Tk, SoundboardABC):
    common_system_button_kwargs = {
        "sticky": "nsew",
        "pady": 1,
        "padx": 3
    }
    def __init__(self, screenName: str | None = None, baseName: str | None = None, className: str = "Tk", useTk: bool = True, sync: bool = False, use: str | None = None) -> None:
        tkinter.Tk.__init__(self, screenName, baseName, className, useTk, sync, use)
        SoundboardABC.__init__(self)

        try:
            self.geometry("700x650")
            self.title("DeveloperJoe Soundboard")
            self.iconphoto(False, tkinter.PhotoImage(file=self.get_media_folder(AppResources.app_image)))        
            self.font: tkfont.Font = tkfont.Font(size=app_font[1], family=app_font[0])
        except tkinter.TclError as error:
            logger.error(f"Missing asset during initisalisation. Error: {error}")
            self.display_error(f"Missing assets. Check log file.")
        
        self.protocol("WM_DELETE_WINDOW", self._handle_close)
        self._kb_listener_thread = SoundboardKeyboardListenerThread(self)
        
        self.set_volume(self.volume)
        self.reload_sounds()
    
    def _handle_close(self):
        if isinstance(self.recording_thread, SoundboardRecordingThread):
            self.recording_thread.stop()
        
        self.stop_audio()
        self.destroy()
        exit(0)
        
    def _handle_audio_end(self, button_ref: pygame.mixer.SoundType, button: SoundboardButton | None):
        try:
            if button:
                button.configure(background=button.master_color)
            self._playing_sounds.remove(button_ref)
        except (tkinter.TclError, ValueError): # User reloaded soundboard, so original button cannot be found
            pass
        
    def _set_all_buttons_default(self, color_name_or_hex: str | None=None) -> None:
        for button in self._sb_buttons:
            button.configure(background=button.master_color if color_name_or_hex == None else color_name_or_hex)
    
    def play_sound(self, button: SoundboardButton | None, sound_file: str | bytes | int) -> None:
        try:
            
            if isinstance(sound_file, str):
                new_sound = pygame.mixer.Sound(file=f"{sound_path}/{sound_file}")
            elif isinstance(sound_file, bytes):
                new_sound = pygame.mixer.Sound(buffer=sound_file)
            elif isinstance(sound_file, int):
                new_sound = pygame.mixer.Sound(file=f"{sound_path}/{self._sb_buttons[sound_file]["text"]}")
                button = self._sb_buttons[sound_file]
            else:
                raise TypeError(f"`sound_file` must be str (path), bytes (Raw PCM), or int (sound index)")
            
            if new_sound.get_length() > 60:
                return self.display_warning(f"Soundboard audio cannot be longer than 60 seconds.")
            if len(self._playing_sounds) > max_sounds_at_once:
                return self.display_warning(f"Cannot play more than {max_sounds_at_once} sounds.")
            
            selected_out = tuple(self.audio_select.curselection())
            device = self.audio_select.get(selected_out[0]) if selected_out else None
            
            if device != self._old_device:
                pygame.mixer.quit()
                pygame.mixer.init(devicename=device)
                
            self._old_device = device
            new_sound.set_volume(self.volume / 100)    
            
            if button:
                button.configure(background="green")
            self._playing_sounds.append(new_sound)
            self._playing_sounds[-1].play()
            
            self.after(int(new_sound.get_length() * 1000), lambda: self._handle_audio_end(new_sound, button))
            
        except pygame.error as err:
            lowered_err = str(err).lower()
            
            if lowered_err == "no such device.":
                self.display_warning(f'Cannot play on selected audio output. Perhaps it was unplugged?')    
                self.reload_sounds()
            elif lowered_err.startswith("no file") == True:
                self.display_warning(f'Cannot find file "{sound_file}"')
                self.reload_sounds()    
            else:
                logger.error(f'Exception playing file "{sound_file}" -> {err}')
                self.display_warning(f'Error decoding file: "{sound_file}" only .wav sound files are supported.')
        
        except FileNotFoundError:
            self.display_warning(f'Missing sound file: "{sound_file}"')
        
        except IndexError:
            pass
        
        except Exception as err:
            logger.error(f"Error playing sound: {err} (File: {sound_file})")
            self.display_warning(f"Error playing sound: {err} (File: {sound_file})")
            if pygame.mixer.get_init():
                pygame.mixer.quit()
                
    def get_avalible_audio_devices(self) -> list[str]:
        pygame.mixer.init()
        return get_audio_device_names(False)
    
    def get_avalible_input_devices(self) -> dict[int, str]:
        
        port_audio = pyaudio.PyAudio()
        info = port_audio.get_host_api_info_by_index(0)                                         
        numdevices = info.get('deviceCount')                                           
        device_dict = {}
        
        if isinstance(numdevices, int):
            for i in range(0, numdevices):
                device_has_input = port_audio.get_device_info_by_index(i).get('maxInputChannels')
                if isinstance(device_has_input, (int, float)) and device_has_input > 0:            
                    device_dict[i] = port_audio.get_device_info_by_index(i).get('name')

        port_audio.terminate()
        return device_dict
        
    def stop_audio(self) -> None:
        # Stops any audio that is playing
        try:
            for sound in self._playing_sounds:
                sound.stop()
            
            self._set_all_buttons_default()
            self._playing_sounds.clear()
            
        except pygame.error as e:
            logging.error(f"Mixer not init? ({e})")
    
    def init(self):
        self.recording_thread = None
        self._sb_buttons.clear()
        self._playing_sounds.clear()
        
    def reload_sounds(self) -> None:
        # Re-renders all buttons
        self.stop_audio()
        self.grid_rowconfigure([row for row in range(config.buttons_per_row + 1)], weight=5)
        
        for button in self._sb_buttons:
            button.destroy()
            
        for i, widget in enumerate(self.winfo_children()):
            self.grid_columnconfigure(i, weight=0)
            widget.destroy()
        
        self.init()
        self.render_sb_buttons()
        self.render_sys_buttons()
        
    def set_font_reload(self, event: tkinter.Event) -> None:
        scale: tkinter.Scale = event.widget
        size = int(scale.get())
        
        if size != int(self.font.actual('size')):
            self.font = tkfont.Font(family=app_font[0], size=int(size))
            self.reload_sounds()
    
    def set_volume(self, volume: int):
        self.volume = volume
        
        for sound in self._playing_sounds:
            sound.set_volume(volume / 100)
    
    def open_sound_folder(self):
        os.system(f"open --reveal {sound_path}/")

    def start_recording(self):
        try:
            input_device_select = tuple(self.input_select.curselection())
            actual_selection_index_name = list(self.input_devices)[input_device_select[0]] if input_device_select and self.input_devices else None
            
            self.record_button.configure(bg="red")
            self.recording_thread = SoundboardRecordingThread(self, input_device_index=actual_selection_index_name)
            self.recording_thread.start()
        except (IndexError, KeyError):
            self.display_error("Was your selected microphone unplugged? Microphone no longer found.")
            self.reload_sounds()
    
    def _set_recording_buttons_highlight(self, on_off: bool):
        
        if on_off == False:
            self.record_button["background"] = self.record_button.master_color
            self.playback_button["background"] = self.playback_button.master_color
            self.save_recording_button["background"] = self.save_recording_button.master_color
        else:
            self.record_button["background"] = "red4"
            self.playback_button["background"] = self.playback_button["activebackground"]
            self.save_recording_button["background"] = self.save_recording_button["activebackground"]
            
    def recording_action(self):
        if isinstance(self.recording_thread, SoundboardRecordingThread):
            if self.recording_thread.has_stopped != True:
                self.recording_thread.stop()
                self._set_recording_buttons_highlight(True)
            else:
                self.recording_thread = None
                self._set_recording_buttons_highlight(False)
                
        else:
            self.start_recording()
    
    def listen_to_playback(self):
        if isinstance(self.recording_thread, SoundboardRecordingThread):            
            self.play_sound(None, self.recording_thread.audio)
    
    def write_playback_as_file(self):
        
        def _get_recorded_name(base_name: str, index: int=0) -> str:
            name = f"{base_name}-{index}.wav"
            if os.path.exists(f"{sound_path}/{name}"):
                return _get_recorded_name(base_name, index + 1)
            return name
            
        self._set_recording_buttons_highlight(False)
        if isinstance(self.recording_thread, SoundboardRecordingThread):
            self.recording_thread.write_to_file(_get_recorded_name("recording"))
            self.recording_thread = None
            
            self.after(500, self.reload_sounds)
            
    def place_slider(self, row: int, column: int, from_: int=0, to: int=60, text: str="Slider", command: Callable=str, configure_kwargs: dict[str, Any]={}, set_value: Any | None=None) -> tkinter.Scale:
        self.grid_columnconfigure(column, weight=1)
        
        slide_label = tkinter.Label(self, text=text, font=self.font, padx=10, pady=5)
        slide_label.grid(row=row, column=column)
        
        scale = tkinter.Scale(self, from_=from_, to=to, orient=tkinter.HORIZONTAL, command=command)
        scale.grid(row=row + 1, column=column, **self.common_system_button_kwargs)
        scale.configure(**configure_kwargs)

        
        scale.set(set_value if set_value else from_)
        
        return scale
    
    def render_sys_buttons(self):

        def next_free_column() -> int:
            c = self._calculate_next_column(self._get_children() + config.buttons_per_row)
            self.grid_columnconfigure(c, weight=4)
            return c
        
        master_color = rgb_to_hex(185, 185, 185)
        system_button_kwargs: dict[str, Any] = {"bg": master_color}
        column = next_free_column()
        sys_background = self.cget("bg")
        
        audio_devices = self.get_avalible_audio_devices()
        self.input_devices = self.get_avalible_input_devices()
        
        common_scale_args = {
            "bd": 0,
            "highlightthickness": 0,
            "font": self.font,
            "bg": sys_background,
            "sliderrelief": "sunken"
        }
        label_args = {
            "relief": tkinter.RAISED,
            "bd": 0,
            "highlightthickness": 0,
            "font": self.font,
            "justify": tkinter.CENTER,
            "bg": sys_background,
            "pady": 40
        }
        
        # Render action buttons (Stop, Reload, Exit, Sound Folder)
        cancel_all = SoundboardSystemButton(self, text="Stop", command=self.stop_audio, activebackground="red", **system_button_kwargs) # Stop
        cancel_all.grid(row=0, column=column, **self.common_system_button_kwargs)
        
        reload = SoundboardSystemButton(self, text="Reload", command=self.reload_sounds, activebackground="yellow", **system_button_kwargs) # Reload
        reload.grid(row=1, column=column, **self.common_system_button_kwargs)
        
        show_sound_folder = SoundboardSystemButton(self, text="Open Sound Folder", command=self.open_sound_folder, activebackground="orange", **system_button_kwargs)
        show_sound_folder.grid(row=2, column=column, **self.common_system_button_kwargs)
        
        self.device_label = tkinter.Label(self, text=f"Output Devices ({len(audio_devices)} Avalible)", **system_button_kwargs)
        self.device_label.grid(row=3, column=column, **self.common_system_button_kwargs)
        self.device_label.configure(**label_args)
        
        self.audio_select = tkinter.Listbox(self, selectmode=tkinter.BROWSE, **system_button_kwargs)
        self.audio_select.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            font=self.font,
            justify=tkinter.CENTER,
            bg=sys_background,
            width=20,
            height=5
        )
        
        for ao_i, audio in enumerate(audio_devices):
            self.audio_select.insert(ao_i + 1, audio)
        else:
            self.audio_select.grid(row=4, column=column, **self.common_system_button_kwargs)
            
        # Sliders (Scale) and Labels for sliders
        
        self.place_slider(row=5, column=column, from_=0, to=100, text="Volume Adj.", command=lambda sound: self.set_volume(int(sound)), configure_kwargs=common_scale_args, set_value=self.volume)
        font_slider = self.place_slider(row=7, column=column, from_=8, to=50, text="Scale Adj.", configure_kwargs=common_scale_args, set_value=self.font.actual('size'))
        font_slider.bind("<ButtonRelease-1>", self.set_font_reload)
        
        # XXX: Second column of system buttons
        
        column += 1
        
        self.record_button = SoundboardSystemButton(self, text="Record / Bin Recording", activebackground="red", command=self.recording_action, **system_button_kwargs)
        self.record_button.grid(row=0, column=column, **self.common_system_button_kwargs)
        
        self.playback_button = SoundboardSystemButton(self, text="Playback Recording", activebackground="light blue", command=self.listen_to_playback, **system_button_kwargs)
        self.playback_button.grid(row=1, column=column, **self.common_system_button_kwargs)
        
        self.save_recording_button = SoundboardSystemButton(self, text="Save Recording", activebackground="light green", command=self.write_playback_as_file, **system_button_kwargs)
        self.save_recording_button.grid(row=2, column=column, **self.common_system_button_kwargs)
        
        self.input_device_label = tkinter.Label(self, text=f"Input Devices ({len(self.input_devices)} Avalible)", **system_button_kwargs)
        self.input_device_label.grid(row=3, column=column, **self.common_system_button_kwargs)
        self.input_device_label.configure(**label_args)
        
        self.input_select = tkinter.Listbox(self, selectmode=tkinter.BROWSE, **system_button_kwargs)
        self.input_select.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            font=self.font,
            justify=tkinter.CENTER,
            bg=sys_background,
            width=20,
            height=5
        )
        
        for ai_i, input in enumerate(self.input_devices.items()):
            self.input_select.insert(ai_i + 1, input[1])
        else:
            self.input_select.grid(row=4, column=column, **self.common_system_button_kwargs)
            
        #end_at_slider = self.place_slider(row=5, column=column, text="Start At", command=lambda a: print("hello"), configure_kwargs=common_scale_args)
        #play_from_slider = self.place_slider(row=7, column=column, text="End At", command=lambda a: print("hello"), configure_kwargs=common_scale_args)
        
        self.update_idletasks()
        self.update()
    
    def _get_children(self) -> int:
        return int(len(list(self.winfo_children())))
    
    def _calculate_next_column(self, c: int | None=None):
        return int((c or self._get_children()) / config.buttons_per_row)
    
    def _calculate_next_row(self, c: int | None=None):
        return int((c or self._get_children()) % config.buttons_per_row)
    
    def render_sb_buttons(self):
        try:
            
            def calculate_and_configure_r_and_c(weight: int=1) -> tuple[int, int]:
                row, column = self._calculate_next_row(), self._calculate_next_column()
                self.grid_columnconfigure(column, weight=weight)
                return (row, column)
        
            # Render each button
            files_abc = os.listdir(sound_path)
            files_abc.sort()
            
            for sound_file in files_abc:
                # Check if it is a sound file
                if sound_file.split(".")[-1] in config.supported_formats:
                    
                    row, column = calculate_and_configure_r_and_c(5)
                    bnt = SoundboardButton(self, text=sound_file, activebackground=rgb_to_hex(190, 190, 190))
                    
                    bnt.grid(row=row, column=column, **common_kwargs)
                    bnt.configure(command=lambda file=sound_file, sb_b=bnt: self.play_sound(sb_b, file))
                    self._sb_buttons.append(bnt)
            
                    
        except FileNotFoundError:
            self.display_error(f'Cannot locate audio file folder: "{sound_path}"')
    
    def change_iconphoto(self, default: bool, image: str) -> None:
        # Changes app icon image, does not do anything if the image does not exist.
        try:
            media = f"{media_path}{image}"
            if os.path.exists(media):
                self.iconphoto(default, tkinter.PhotoImage(file=media))
        except tkinter.TclError:
            logger.error(f"Cannot create iconphoto with media: {image}")
            return
    
    @SoundboardDecorators.change_image_warning
    def display_warning(self, message: str) -> None:
        messagebox.showwarning("Warning", message)
    
    @SoundboardDecorators.change_image_error
    def display_error(self, message: str) -> NoReturn:
        messagebox.showerror("Error", message)
        exit(1)
        
    def get_media_folder(self, asset_name: str) -> str:
        return self.assure_path(f"{media_path}{asset_name}")
    
    def assure_path(self, path: str) -> str:
        if os.path.exists(path):
            return path
        return self.display_error(f"Missing asset: {path}")
    
if __name__ == "__main__":
    from platform import platform
    sys_platform = platform().startswith("macOS")
        
    Soundboard().mainloop()