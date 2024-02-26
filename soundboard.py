import tkinter, tkmacosx, yaml, logging, os, math, dataclasses, pygame, random

from typing import Any, NoReturn, Callable
from tkinter import messagebox
from abc import ABC, abstractmethod

logger = logging.getLogger(__file__)
logger.setLevel(logging.DEBUG)
pygame.mixer.init()

file_handler = logging.FileHandler("./configuration/dj_soundboard.log", mode="w+")
file_handler.setLevel(logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')    
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
configuration_file = "configuration/soundboard_config.yml"

@dataclasses.dataclass
class SoundboardConfig:
    sound_folder: str
    media_folder: str
    window_title: str
    supported_formats: list[str]
    buttons_per_row: int
    error_image: str
    app_image: str
    warning_image: str

# Global functions

def get_and_gen_yaml() -> dict[str, Any]:
    default_config = {
        "sound_folder": "./audio",
        "media_folder": "./media/",
        "window_title": "DeveloperJoe Soundboard",
        "supported_formats": ["wav", "mp3", "ogg"], # Wav, ogg and mp3 only.
        "buttons_per_row": 5,
        "error_image": "bear.png",
        "app_image": "speaker.wave.3.png",
        "warning_image": "why.png"
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
config = SoundboardConfig(**get_and_gen_yaml())
common_kwargs = {"sticky": "nsew", "pady": 1}

class SoundboardABC(ABC):
    # Soundboard ABC. Basically just for type annotations
    
    def __init__(self) -> None:
        super().__init__()
        
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
            self.change_iconphoto(False, config.error_image)
            func_out = func(self, *args, **kwargs)
            self.change_iconphoto(False, config.app_image)
            
            return func_out
        return _inner

    @staticmethod
    def change_image_warning(func: Callable) -> Callable:
        def _inner(self: SoundboardABC, *args, **kwargs) -> Any:
            self.change_iconphoto(False, config.warning_image)
            func_out = func(self, *args, **kwargs)
            self.change_iconphoto(False, config.app_image)
            
            return func_out
        return _inner

class SoundboardButton(tkmacosx.Button, tkinter.Button): # NOTE: Inheriting from tkinter.Button so VSCode Intellisense functions correctly. It does not with tkmacos. tkinter.Button does not provide any functionality.
    def __init__(self, master=None, cnf=..., **kw):
        tkmacosx.Button.__init__(self, master, cnf, **kw)
        self.master_color = self._org_bg
        

        self.configure(
            relief=tkinter.RAISED,
            bd=0,
            highlightthickness=0,
            pady=50,
            font=("DINAlternate-Bold", 18),
            highlightbackground=self.master_color,
            highlightcolor=self.master_color
        )
        
        self.bind("<Enter>", self.on_elem_enter)
        self.bind("<Leave>", self.on_elem_exit)
    
    def on_elem_enter(self, event: tkinter.Event) -> None:
        self.configure(background=default_highlight_color)
    
    def on_elem_exit(self, event: tkinter.Event) -> None:
        self.configure(background=self.master_color)
        
class Soundboard(tkinter.Tk, SoundboardABC):
    def __init__(self, screenName: str | None = None, baseName: str | None = None, className: str = "Tk", useTk: bool = True, sync: bool = False, use: str | None = None) -> None:
        tkinter.Tk.__init__(self, screenName, baseName, className, useTk, sync, use)
        SoundboardABC.__init__(self)
        
        self.geometry("600x600")
        self.title(config.window_title)
        self.iconphoto(False, tkinter.PhotoImage(file=self.get_media_folder(config.app_image)))
        
        self.render_sb_buttons()
    
    def play_sound(self, sound_file: str) -> None:
        try:
            pygame.mixer.music.load(f"{config.sound_folder}/{sound_file}")
            pygame.mixer.music.play()
        except pygame.error as err:
            logger.error(f'Exception playing file "{sound_file}" -> {err}')
            self.display_warning(f'Error decoding file: "{sound_file}" only .wav sound files are supported.')
        except FileNotFoundError:
            self.display_warning(f'Missing sound file: "{sound_file}"')
    
    def stop_audio(self) -> None:
        # Stops any audio that is playing
        pygame.mixer.music.stop()
    
    def reload_sounds(self) -> None:
        # Re-renders all buttons
        for widget in self.winfo_children():
            widget.destroy()
            
        self.render_sb_buttons()
        
    def render_sb_buttons(self):
        get_children = lambda: int(len(list(self.winfo_children())))
        try:
            calculate_next_row = lambda c=None: int((c or get_children()) % config.buttons_per_row)
            calculate_next_column = lambda c=None: int((c or get_children()) / config.buttons_per_row)
            
            def calculate_and_configure_r_and_c(predefined_child_count: int | None=None, weight: int=1) -> tuple[int, int]:
                row, column = calculate_next_row(predefined_child_count), calculate_next_column(predefined_child_count)
                self.grid_rowconfigure(row, weight=weight)
                self.grid_columnconfigure(column, weight=weight)
                return (row, column)
            
            sound_file: str
            
            # Render each button
            # TODO: Make next_free_column function for making all operating buttons on the same column
            for sound_file in os.listdir(config.sound_folder):
                # Check if it is a sound file
                if sound_file.split(".")[-1] in config.supported_formats:
                    
                    row, column = calculate_and_configure_r_and_c(weight=5)
                                
                    bnt = SoundboardButton(self, text=sound_file, command=lambda file=sound_file: self.play_sound(file), activebackground=rgb_to_hex(190, 190, 190))
                    bnt.grid(row=row, column=column, **common_kwargs)

            else:
                # Render action buttons (Reload, stop)
                
                system_button_kwargs: dict[str, Any] = {"bg": rgb_to_hex(200, 200, 200)}
                
                row, column = calculate_and_configure_r_and_c() 
                cancel_all = SoundboardButton(self, text="Stop", command=self.stop_audio, activebackground="red", **system_button_kwargs)
                cancel_all.grid(row=row, column=column, **common_kwargs)
                
                row, column = calculate_and_configure_r_and_c()
                reload = SoundboardButton(self, text="Reload", command=self.reload_sounds, activebackground="yellow", **system_button_kwargs)
                reload.grid(row=row, column=column, **common_kwargs)
                
                row, column = calculate_and_configure_r_and_c()
                exit = SoundboardButton(self, text="Exit", command=self.destroy, activebackground="black", **system_button_kwargs)
                exit.grid(row=row, column=column, **common_kwargs)
                
        except FileNotFoundError:
            self.display_error(f'Cannot locate audio file folder: "{config.sound_folder}"')
    
    def change_iconphoto(self, default: bool, image: str) -> None:
        # Changes app icon image, does not do anything if the image does not exist.
        try:
            media = f"{config.media_folder}{image}"
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
        return self.assure_path(f"{config.media_folder}{asset_name}")
    
    def assure_path(self, path: str) -> str:
        if os.path.exists(path):
            return path
        return self.display_error(f"Missing asset: {path}")
    
if __name__ == "__main__":
    Soundboard().mainloop()