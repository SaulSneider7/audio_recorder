import customtkinter as ctk
import pyaudiowpatch as audio
import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime
import threading, queue, time, wave, os, subprocess
import imageio_ffmpeg

QUALITIES = {"MP3 · Baja (64 kbps)": 64, "MP3 · Media (128 kbps)": 128, "MP3 · Alta (192 kbps)": 192, "MP3 · Máxima (320 kbps)": 320, "WAV · Original": None}

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')

class Recorder(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('PC Audio Recorder')
        self.geometry('640x640')
        self.minsize(550, 620)
        self.configure(fg_color='#10131d')
        self.folder = Path.home() / 'PC Audio Recordings'
        self.events = queue.SimpleQueue()
        self.stop_event = threading.Event()
        self.worker = None
        self.started = None
        self.closing = False
        self.level = 0.0
        self.history = [0.0]*48
        self.last_file = None
        ctk.CTkLabel(self, text='PC Audio Recorder', font=ctk.CTkFont(size=29, weight='bold'), text_color='#eeeaff').pack(pady=(25, 2))
        ctk.CTkLabel(self, text='Captura de audio interno · Windows WASAPI', text_color='#a5a9ba').pack()
        self.status = ctk.CTkLabel(self, text='●  Listo para grabar', text_color='#67d9a1')
        self.status.pack(pady=(18,0))
        self.clock = ctk.CTkLabel(self, text='00:00:00', font=ctk.CTkFont(size=48, weight='bold'))
        self.clock.pack()
        self.canvas = tk.Canvas(self, height=75, bg='#10131d', highlightthickness=0)
        self.canvas.pack(fill='x', padx=36, pady=(4,12))
        controls = ctk.CTkFrame(self, fg_color='transparent')
        controls.pack(fill='x', padx=30, pady=5)
        controls.grid_columnconfigure((0,1), weight=1)
        self.start_btn = ctk.CTkButton(controls, text='●  Iniciar grabación', height=48, fg_color='#7544de', hover_color='#6635cc', command=self.start)
        self.start_btn.grid(row=0,column=0,sticky='ew',padx=(0,6))
        self.stop_btn = ctk.CTkButton(controls, text='■  Detener', height=48, fg_color='#a83150', hover_color='#88243e', state='disabled', command=self.stop)
        self.stop_btn.grid(row=0,column=1,sticky='ew',padx=(6,0))
        panel = ctk.CTkFrame(self, fg_color='#1d2230', corner_radius=14)
        panel.pack(fill='x', padx=30, pady=15)
        ctk.CTkLabel(panel, text='CONFIGURACIÓN DE AUDIO', text_color='#a5a9ba').pack(anchor='w', padx=16, pady=(12,0))
        self.device = ctk.CTkLabel(panel, text='Salida predeterminada de Windows', wraplength=480, justify='left')
        self.device.pack(anchor='w', padx=16, pady=4)
        self.quality = ctk.CTkOptionMenu(panel, values=list(QUALITIES), fg_color='#34394b', button_color='#7544de')
        self.quality.set('MP3 · Media (128 kbps)')
        self.quality.pack(fill='x', padx=16, pady=5)
        self.folder_label = ctk.CTkLabel(panel, text=str(self.folder), wraplength=480, justify='left', text_color='#b9b9c9')
        self.folder_label.pack(anchor='w', padx=16, pady=(8,3))
        buttons = ctk.CTkFrame(panel, fg_color='transparent')
        buttons.pack(fill='x', padx=16, pady=(3,12))
        self.choose_btn = ctk.CTkButton(buttons,text='Cambiar carpeta',fg_color='#34394b',command=self.choose_folder)
        self.choose_btn.pack(side='left', padx=(0,8))
        ctk.CTkButton(buttons,text='Abrir carpeta',fg_color='#34394b',command=self.open_folder).pack(side='left')
        self.result = ctk.CTkLabel(self,text='Micrófono excluido de la captura', text_color='#a5a9ba',wraplength=500)
        self.result.pack(padx=20)
        self.protocol('WM_DELETE_WINDOW', self.close_app)
        self.after(70, self.tick)

    def choose_folder(self):
        selected = filedialog.askdirectory(initialdir=str(self.folder if self.folder.exists() else Path.home()))
        if selected:
            self.folder = Path(selected)
            self.folder_label.configure(text=selected)

    def open_folder(self):
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(self.folder))
        except OSError as e:
            messagebox.showerror('Error', str(e))

    def start(self):
        if self.worker is not None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            messagebox.showerror('Error', str(e)); return
        bitrate = QUALITIES[self.quality.get()]
        extension = '.mp3' if bitrate else '.wav'
        path = self.folder / (datetime.now().strftime('Audio_%Y-%m-%d_%H-%M-%S_%f') + extension)
        self.stop_event.clear()
        self.started = None
        self.clock.configure(text='00:00:00')
        self.history = [0.0]*48
        self.start_btn.configure(state='disabled')
        self.choose_btn.configure(state='disabled')
        self.quality.configure(state='disabled')
        self.stop_btn.configure(state='normal')
        self.status.configure(text='●  Conectando al audio...',text_color='#f4c66a')
        self.result.configure(text='Preparando grabación...')
        self.worker = threading.Thread(target=self.capture,args=(path,bitrate),daemon=False)
        self.worker.start()

    def capture(self, path, bitrate):
        partial = path.with_suffix('.partial.wav')
        error = None
        try:
            with audio.PyAudio() as p:
                dev = p.get_default_wasapi_loopback()
                channels = int(dev['maxInputChannels'])
                rate = int(dev['defaultSampleRate'])
                if channels < 1 or not dev.get('isLoopbackDevice'):
                    raise RuntimeError('No se encontró una salida de audio loopback válida.')
                with wave.open(str(partial),'wb') as wf:
                    wf.setnchannels(channels)
                    wf.setsampwidth(2)
                    wf.setframerate(rate)
                    callback_error = []
                    def callback(data, count, info, flags):
                        if self.stop_event.is_set():
                            return (None, audio.paComplete)
                        try:
                            wf.writeframesraw(data)
                            samples = np.frombuffer(data,dtype='<i2').astype(np.float32)/32768
                            self.level = float(np.sqrt(np.mean(samples*samples))) if samples.size else 0.0
                        except Exception as e:
                            callback_error.append(str(e))
                            return (None,audio.paAbort)
                        return (None,audio.paContinue)
                    with p.open(format=audio.paInt16,channels=channels,rate=rate,input=True,input_device_index=dev['index'],frames_per_buffer=1024,stream_callback=callback,start=False) as stream:
                        if not self.stop_event.is_set():
                            stream.start_stream()
                            self.events.put(('started',(dev['name'],rate,channels)))
                            while not self.stop_event.wait(.05) and stream.is_active():
                                pass
                            if stream.is_active():
                                stream.stop_stream()
                        if callback_error:
                            raise RuntimeError(callback_error[0])
                        if not self.stop_event.is_set():
                            raise RuntimeError('La salida de audio se desconectó o dejó de funcionar.')
            with wave.open(str(partial),'rb') as check:
                frames = check.getnframes()
            if not frames:
                partial.unlink(missing_ok=True)
                raise RuntimeError('No se recibió audio. Reproduce sonido e inténtalo nuevamente.')
            if bitrate:
                self.events.put(('encoding', None))
                encoded = path.with_suffix('.partial.mp3')
                try:
                    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(partial), '-vn', '-ac', '2', '-c:a', 'libmp3lame', '-b:a', f'{bitrate}k', str(encoded)]
                    process = subprocess.run(command, capture_output=True, text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if process.returncode or not encoded.exists() or not encoded.stat().st_size:
                        raise RuntimeError('No se pudo convertir a MP3: ' + process.stderr.strip())
                    encoded.replace(path)
                finally:
                    encoded.unlink(missing_ok=True)
                partial.unlink()
            else:
                partial.replace(path)
        except Exception as e:
            error = str(e)
        finally:
            self.level = 0.0
            self.events.put(('done',(path if path.exists() else None, error, partial if partial.exists() else None)))

    def stop(self):
        self.stop_event.set()
        self.stop_btn.configure(state='disabled')
        self.status.configure(text='●  Guardando...',text_color='#f4c66a')

    def tick(self):
        while True:
            try: kind, data = self.events.get_nowait()
            except queue.Empty: break
            if kind == 'started':
                name, rate, channels = data
                self.started = time.monotonic()
                self.device.configure(text=f'{name}\n{rate} Hz · {channels} canales')
                if not self.stop_event.is_set():
                    self.status.configure(text='●  Grabando audio interno',text_color='#fb7185')
            elif kind == 'encoding':
                self.started = None
                self.status.configure(text='●  Convirtiendo a MP3...', text_color='#f4c66a')
            elif kind == 'done':
                path, error, partial = data
                self.worker = None
                self.started = None
                self.start_btn.configure(state='normal')
                self.choose_btn.configure(state='normal')
                self.quality.configure(state='normal')
                self.stop_btn.configure(state='disabled')
                if error:
                    self.status.configure(text='●  Grabación interrumpida',text_color='#fb7185')
                    self.result.configure(text=error)
                    messagebox.showwarning('Grabación',error + (f'\nArchivo parcial: {partial}' if partial else ''))
                else:
                    self.last_file = path
                    self.status.configure(text='●  Grabación guardada',text_color='#67d9a1')
                    self.result.configure(text=path.name)
                if self.closing:
                    self.destroy(); return
        if self.started is not None:
            seconds = int(time.monotonic()-self.started)
            self.clock.configure(text=f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')
        self.history = self.history[1:] + [min(1.0,self.level*4) if self.started is not None else 0.0]
        self.canvas.delete('all')
        w = self.canvas.winfo_width(); h = self.canvas.winfo_height(); step = w/len(self.history)
        for i,v in enumerate(self.history):
            height = 3+v*(h-8); x = (i+.5)*step
            self.canvas.create_line(x,(h-height)/2,x,(h+height)/2,fill='#a78bfa',width=max(2,step*.55),capstyle='round')
        self.after(70,self.tick)

    def close_app(self):
        if self.worker is not None:
            if messagebox.askyesno('Salir','¿Detener la grabación, guardar y salir?'):
                self.closing = True
                self.stop()
        else:
            self.destroy()

if __name__ == '__main__':
    Recorder().mainloop()
