import tkinter, tkmacosx, yaml, logging, os, dataclasses, pygame, pdb, tempfile

from typing import Any, NoReturn, Callable
from tkinter import messagebox
from abc import ABC, abstractmethod

from tkinter import font as tkfont
from pygame._sdl2.audio import get_audio_device_names

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

@dataclasses.dataclass
class SoundboardConfig:
    supported_formats: list[str]
    buttons_per_row: int
    default_volume: float
    default_font_size: int

class AppResources:
    warning_image = "why.png"
    app_image = "512-mac.png"
    error_image = "bear.png"

# Global functions
def get_and_gen_yaml() -> dict[str, Any]:
    
    default_config = {
        "supported_formats": ["wav", "mp3", "ogg"], # Wav, ogg and mp3 only.
        "buttons_per_row": 5,
        "default_volume": 0.5,
        "default_font_size": 18 
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
    app_font = ("DINAlternate-Bold", config.default_font_size)
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
        
        self.device_label = None
        self.after_id = None
        self.volume = config.default_volume
        
    @abstractmethod
    def change_iconphoto(self, default: bool, image: str) -> None:
        pass

    @abstractmethod
    def display_error(self, message: str) -> NoReturn: # type: ignore abc method
        pass
    
    @abstractmethod
    def display_warning(self, message: str) -> None:
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

class SoundboardButton(tkmacosx.Button, tkinter.Button): # NOTE: Inheriting from tkinter.Button so VSCode Intellisense functions correctly. It does not with tkmacos. tkinter.Button does not provide any functionality.
    def __init__(self, master, cnf=..., **kw):
        tkmacosx.Button.__init__(self, master, cnf, **kw)
        self.master_color = self._org_bg


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
    
    def on_elem_enter(self, event: tkinter.Event) -> None:
        if not pygame.mixer.get_busy():
            self.configure(background=default_highlight_color)
    
    def on_elem_exit(self, event: tkinter.Event) -> None:
        if not pygame.mixer.get_busy():
            self.configure(background=self.master_color)
         
class Soundboard(tkinter.Tk, SoundboardABC):
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
                
        self.set_volume(self.volume)
        self.reload_sounds()
    
    def _handle_audio_end(self, button_ref: pygame.mixer.SoundType, button: SoundboardButton):
        try:
            button.configure(background=button.master_color)
            self._playing_sounds.remove(button_ref)
        except (tkinter.TclError, ValueError): # User reloaded soundboard, so original button cannot be found
            pass
        
    def _set_all_buttons_default(self, color_name_or_hex: str | None=None) -> None:
        for button in self._sb_buttons:
            button.configure(background=button.master_color if color_name_or_hex == None else color_name_or_hex)
    
    def play_sound(self, button: SoundboardButton, sound_file: str) -> None:
        try:
            if len(self._playing_sounds) > max_sounds_at_once:
                return self.display_warning(f"Cannot play more than {max_sounds_at_once} sounds.")
            
            selected_out = tuple(self.audio_select.curselection())
            device = self.audio_select.get(selected_out[0]) if selected_out else None
            
            if device != self._old_device:
                pygame.mixer.quit()
                pygame.mixer.init(devicename=device)
                
            self._old_device = device
            new_sound = pygame.mixer.Sound(f"{sound_path}/{sound_file}")
            new_sound.set_volume(self.volume / 100)    
            
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
            
        except Exception as err:
            logger.error(f"Error playing sound: {err} (File: {sound_file})")
            if pygame.mixer.get_init():
                pygame.mixer.quit()
                
    def get_avalible_audio_devices(self) -> list[str]:
        pygame.mixer.init()
        return get_audio_device_names(False)
    
    def stop_audio(self) -> None:
        # Stops any audio that is playing
        try:
            for sound in self._playing_sounds:
                sound.stop()
            
            self._set_all_buttons_default()
            self._playing_sounds.clear()
            
        except pygame.error as e:
            logging.error(f"Mixer not init? ({e})")
            
    def reload_sounds(self) -> None:
        # Re-renders all buttons
        self.stop_audio()
        self.grid_rowconfigure([row for row in range(config.buttons_per_row)], weight=5)
        
        for button in self._sb_buttons:
            button.destroy()
            
        for i, widget in enumerate(self.winfo_children()):
            self.grid_columnconfigure(i, weight=0)
            widget.destroy()
            
        self._sb_buttons.clear()
        self._playing_sounds.clear()
        
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
        
    def render_sys_buttons(self):

        def next_free_column() -> int:
            c = self._calculate_next_column(self._get_children() + config.buttons_per_row)
            self.grid_columnconfigure(c, weight=1)
            return c
        
        # Render action buttons (Reload, stop)
        common_system_button_kwargs = {
            "sticky": "nsew",
            "pady": 1,
            "padx": 3
        }
        
        master_color = rgb_to_hex(200, 200, 200)
        system_button_kwargs: dict[str, Any] = {"bg": master_color}
        column = next_free_column()
        sys_background = self.cget("bg")
        
        cancel_all = SoundboardButton(self, text="Stop", command=self.stop_audio, activebackground="red", **system_button_kwargs)
        cancel_all.grid(row=0, column=column, **common_system_button_kwargs)
        
        reload = SoundboardButton(self, text="Reload", command=self.reload_sounds, activebackground="yellow", **system_button_kwargs)
        reload.grid(row=1, column=column, **common_system_button_kwargs)
        
        exit = SoundboardButton(self, text="Exit", command=self.destroy, activebackground="black", **system_button_kwargs)
        exit.grid(row=2, column=column, **common_system_button_kwargs)
        
        show_sound_folder = SoundboardButton(self, text="Open Sound Folder", command=self.open_sound_folder, activebackground="white", **system_button_kwargs)
        show_sound_folder.grid(row=3, column=column, **common_system_button_kwargs)
        
        # Sliders (Scale) and Labels for sliders
        
        # Volume Slider
        volume_label = tkinter.Label(self, text="Volume Adj.", padx=10, pady=5, font=self.font)
        volume_label.grid(row=6, column=column)
        
        audio_slider = tkinter.Scale(self, from_=0, to=100, orient=tkinter.HORIZONTAL, command=lambda sound: self.set_volume(int(sound))) # Volume
        audio_slider.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            font=self.font,
            bg=sys_background,
            sliderrelief="sunken",
        )
        audio_slider.grid(row=7, column=column, sticky="we", padx=10, pady=5)
        audio_slider.set(self.volume)
        
        # Font Slider
        font_label = tkinter.Label(self, text="Scale Adj.", padx=10, pady=5, font=self.font)
        font_label.grid(row=8, column=column)
        
        font_slider = tkinter.Scale(self, from_=8, to=50, orient=tkinter.HORIZONTAL) # Font
        font_slider.set(int(self.font.actual('size')))
        font_slider.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            font=self.font,
            bg=sys_background,
            sliderrelief="sunken"
        )
        font_slider.bind("<ButtonRelease-1>", self.set_font_reload)
        font_slider.grid(row=9, column=column, sticky="we", padx=10, pady=5)
        
        # Audio
        audio_devices = self.get_avalible_audio_devices()
        self.device_label = tkinter.Label(self, text=f"Output Devices ({len(audio_devices)} Avalible)", **system_button_kwargs)
        self.device_label.grid(row=4, column=column, **common_system_button_kwargs)
        self.device_label.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            font=self.font,
            justify=tkinter.CENTER,
            bg=sys_background,
            pady=40
        )
        
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
            self.audio_select.grid(row=5, column=column, **common_system_button_kwargs)
        
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
            for sound_file in os.listdir(sound_path):
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
    
    if not sys_platform:
        print(f"Incorrect platform ({sys_platform}) macOS only.")
        exit(1)
    Soundboard().mainloop()