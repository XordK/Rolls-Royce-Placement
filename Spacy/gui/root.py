import csv
import logging
import ctypes as ct
import tkinter as tk
from tkinter import filedialog, messagebox
from threading import Thread
from urllib.parse import urlparse
from appdirs import AppDirs
from requests.exceptions import (
    ConnectionError as RequestsConnectionError
)
from spacy.language import Language
from spacy import load as get_pipe
from utils import parse_string_content, web_scrape
from constants import ASSETS_PATH
from config import ConfigManager
from .addressbar import AddressBar
from .notebook import Notebook
from .style import Style


log = logging.getLogger(__name__)


class Root(tk.Tk):
    """Root of the GUI application"""
    _content_title: str
    _unparsed: str
    _parsed: list[list[str]]
    pipeline: Language

    def __init__(self, name:str, dirs:AppDirs, restart_func):
        super().__init__()
        self.dirs = dirs
        self.cfg = ConfigManager(dirs)
        self.restart = restart_func

        # Configure root window
        self.title(name)
        self.geometry('700x400')
        self.minsize(500, 370)
        self.iconbitmap(f'{ASSETS_PATH}/icon.ico')

        # Create and show controls
        self.notebook = Notebook(self)
        self.addbar = AddressBar(self)
        self.addbar.pack(fill='x')
        self.notebook.pack(fill='both', expand=True)

        # Initialize style
        self.style = Style(self)

        # Change titlebar to dark variant (win11 only)
        if self.notebook.settings_tab.colour_mode.get() == 'dark':
            self.set_dark_titlebar()

        # Debug Binds
        self.bind_all('<F1>', self.debug_show_geometry, add=True)
        self.bind_all('<F2>', self.debug_clear_results, add=True)

    def debug_show_geometry(self, event=None):
        print(
            'Width:', self.winfo_width(),
            '\nHeight:', self.winfo_height()
        )

    def debug_clear_results(self, event=None):
        nb = self.notebook
        nb.results_tab.tree.delete(*nb.results_tab.tree.get_children())
        nb.contents_tab.content_field.config(text='')

    def set_dark_titlebar(self):
        """(Windows 11 Only) Change titlebar to dark variant"""
        value = ct.c_int(2)
        # I wish I knew how ctypes worked internally but I don't
        # TODO: learn ctypes to implement better commenting
        ct.windll.dwmapi.DwmSetWindowAttribute(
            ct.windll.user32.GetParent(self.winfo_id()),
            20, ct.byref(value), ct.sizeof(value)
        )

    def start(self):
        """Start the GUI application"""
        self.mainloop()

    def import_string(self) -> tuple[str, str]:
        """Import a string from a text file and return it"""
        log.debug('Importing string from text file')
        # Open existing file to read from
        file = filedialog.askopenfile(
            defaultextension='.txt',
            filetypes=(('Text File', '*.txt'),)
        )
        # Return if no file is selected
        if not file: return "No file selected" , ""
        data = file.read()
        file.close()
        log.debug('Successfully import string from text file')
        return file.name, data

    def export_results(self):
        """Export results from results tab to file"""
        log.debug('Exporting results to output file')
        # Create and open the output file
        file = filedialog.asksaveasfile(
            initialfile='output.csv',
            defaultextension='.csv',
            filetypes=(('CSV File', '*.csv'),)
        )
        # Return if no output file has been selected
        if not file: return
        # Collect data from results treeview
        tree = self.notebook.results_tab.tree
        tree_data = [
            tree.item(row)['values'] \
            for row in tree.get_children()
        ]
        # Write data to output file
        writer = csv.writer(file)
        writer.writerows(tree_data)
        file.close()
        log.info(f'Exported {len(tree_data)} rows to {file.name}')

    def nlp(self, address:str):
        """Collect, parse and output data to results tab"""
        nb = self.notebook
        absolute_url = bool(urlparse(address).netloc)
        self.addbar.update_gui_state(searching=True)

        def connection_error(url:str):
            log.error(f"couldn't establish connection with {url}")
            self.addbar.update_gui_state(searching=False)
            messagebox.showerror(
                title='Connection Error',
                message="Couldn't establish an internet connection. " \
                        "Please check your internet connection and " \
                        "try again."
            )

        def pipeline_loading():
            log.error('Attempted nlp before pipeline was loaded')
            self.addbar.update_gui_state(searching=False)
            messagebox.showerror(
                title='Pipeline Error',
                message='Cannot do that right now because the ' \
                        'pipeline has not been loaded. Try again soon.'
            )

        def get_content_absolute():
            return web_scrape(
                address, remove_linebreak=True
            )

        def get_content_non_absolute():
            try:
                with open(address, 'r') as file:
                    title = address.split('/')[-1]
                    content = file.read()
            except FileNotFoundError:
                return 'Content Not Found', ''
            title = title.split('.')[0].replace('_', ' ').title()
            return title, content

        def thread_func():
            try:
                self._content_title, content = get_content_absolute() \
                    if absolute_url else get_content_non_absolute()
            except RequestsConnectionError:
                connection_error()
                return
            self._unparsed = "".join(content)
            try:
                self._parsed = parse_string_content(
                    pipeline=self.pipeline,
                    string=self._unparsed
                )
            except AttributeError:
                pipeline_loading()
                return
            log.info('Finished parsing content')

        def check_thread_finished(thread, ms:int):
            if thread.is_alive():
                self.after(ms, lambda: check_thread_finished(thread, ms))
                return
            try:
                output_result()
            except AttributeError as e:
                log.error(f'Attribute error: {e}')
                return

        def output_result():
            nb.contents_tab.update_content(
                self._content_title, self._unparsed
            )
            nb.results_tab.update_tree(
                self._content_title, self._parsed
            )
            self.addbar.update_gui_state(searching=False)
            if nb.settings_tab.auto_save.get():
                nb.results_tab.save()

        thread = Thread(target=thread_func)
        thread.daemon = True
        thread.start()
        check_thread_finished(thread, ms=1000)
