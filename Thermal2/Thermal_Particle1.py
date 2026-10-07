from queue import Empty, Queue
import random
from threading import Thread
import time
import cv2
import numpy as np
from PIL import Image, ImageTk
import pygame
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import messagebox, ttk

BAUD = 500000

# Initialize Pygame Mixer for procedural audio
pygame.mixer.init(frequency=22050, size=-16, channels=1)

COLORMAPS = [
    ("Jet (Ironbow-like)", cv2.COLORMAP_JET),
    ("Turbo", cv2.COLORMAP_TURBO),
    ("Inferno", cv2.COLORMAP_INFERNO),
    ("Magma", cv2.COLORMAP_MAGMA),
]


class ThermalStreamApp:

  def __init__(self, root):
    self.root = root
    self.root.title("ESP32 Thermal Stream Viewer & Micro-Climate Ecosystem")
    self.root.geometry("520x450")
    self.root.resizable(False, False)

    self.ser = None
    self.running = False
    self.frame_queue = Queue(maxsize=2)
    self.current_cmap_idx = 0
    self.countdown_val = 0
    self.burst_count_remaining = 0

    # Ecosystem State
    self.ecosystem_active = False
    self.particles = []

    # --- COM Port Selection Screen ---
    self.setup_frame = tk.Frame(root, padx=20, pady=20)
    self.setup_frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        self.setup_frame,
        text="Choose ESP32 COM Port:",
        font=("Arial", 12, "bold"),
    ).pack(pady=15)

    self.port_combobox = ttk.Combobox(
        self.setup_frame, state="readonly", width=30, font=("Arial", 10)
    )
    self.port_combobox.pack(pady=5)
    self.refresh_ports()

    tk.Button(
        self.setup_frame,
        text="Connect & Launch Viewer",
        bg="#4CAF50",
        fg="white",
        font=("Arial", 11, "bold"),
        padx=10,
        pady=5,
        command=self.connect_device,
    ).pack(pady=20)

  def refresh_ports(self):
    ports = [port.device for port in serial.tools.list_ports.comports()]
    if not ports:
      ports = ["No ports found"]
    self.port_combobox["values"] = ports
    self.port_combobox.current(0)

  def connect_device(self):
    selected_port = self.port_combobox.get()
    if not selected_port or "No ports" in selected_port:
      messagebox.showerror(
          "Connection Error", "Please select a valid serial port."
      )
      return

    try:
      self.ser = serial.Serial(selected_port, BAUD, timeout=1)
    except Exception as e:
      messagebox.showerror("Connection Error", f"Failed to open port: {e}")
      return

    self.setup_frame.destroy()
    self.build_dashboard()

    self.running = True
    self.reader_thread = Thread(target=self.read_serial_stream, daemon=True)
    self.reader_thread.start()
    self.update_gui()

  def build_dashboard(self):
    self.root.geometry("640x550")

    self.canvas_label = tk.Label(self.root, bg="black")
    self.canvas_label.place(x=20, y=20, width=480, height=360)

    telemetry_frame = tk.Frame(self.root, padx=10)
    telemetry_frame.place(x=510, y=20, width=120, height=360)

    tk.Label(
        telemetry_frame, text="MAX:", font=("Arial", 9, "bold"), fg="red"
    ).pack(anchor="w")
    self.lbl_max = tk.Label(
        telemetry_frame, text="--.- C", font=("Arial", 10)
    )
    self.lbl_max.pack(anchor="w", pady=(0, 10))

    tk.Label(
        telemetry_frame, text="MIN:", font=("Arial", 9, "bold"), fg="blue"
    ).pack(anchor="w")
    self.lbl_min = tk.Label(
        telemetry_frame, text="--.- C", font=("Arial", 10)
    )
    self.lbl_min.pack(anchor="w", pady=(0, 10))

    tk.Label(
        telemetry_frame, text="CENTRE:", font=("Arial", 9, "bold"), fg="green"
    ).pack(anchor="w")
    self.lbl_centre = tk.Label(
        telemetry_frame, text="--.- C", font=("Arial", 10)
    )
    self.lbl_centre.pack(anchor="w", pady=(0, 20))

    self.lbl_cmap = tk.Label(
        telemetry_frame,
        text=f"Map:\n{COLORMAPS[self.current_cmap_idx][0]}",
        font=("Arial", 8),
        justify="left",
    )
    self.lbl_cmap.pack(anchor="w")

    btn_frame = tk.Frame(self.root, pady=10)
    btn_frame.place(x=20, y=390, width=600, height=130)

    row1 = tk.Frame(btn_frame)
    row1.pack(fill=tk.X, pady=2)

    tk.Button(
        row1,
        text="Save Snapshot",
        bg="#2196F3",
        fg="white",
        font=("Arial", 9, "bold"),
        width=16,
        command=self.save_snapshot,
    ).pack(side=tk.LEFT, padx=5)

    tk.Button(
        row1,
        text="Snap (3s Delay)",
        bg="#9C27B0",
        fg="white",
        font=("Arial", 9, "bold"),
        width=16,
        command=self.start_delayed_snapshot,
    ).pack(side=tk.LEFT, padx=5)

    tk.Button(
        row1,
        text="Burst Snap (5x)",
        bg="#E91E63",
        fg="white",
        font=("Arial", 9, "bold"),
        width=16,
        command=self.start_burst_snapshot,
    ).pack(side=tk.LEFT, padx=5)

    row2 = tk.Frame(btn_frame)
    row2.pack(fill=tk.X, pady=5)

    tk.Button(
        row2,
        text="Change Colormap",
        bg="#FF9800",
        fg="white",
        font=("Arial", 9, "bold"),
        width=15,
        command=self.cycle_colormap,
    ).pack(side=tk.LEFT, padx=2)

    self.btn_ecosystem = tk.Button(
        row2,
        text="Ecosystem: OFF",
        bg="#607D8B",
        fg="white",
        font=("Arial", 9, "bold"),
        width=16,
        command=self.toggle_ecosystem,
    )
    self.btn_ecosystem.pack(side=tk.LEFT, padx=5)

    tk.Button(
        row2,
        text="Exit",
        bg="#F44336",
        fg="white",
        font=("Arial", 9, "bold"),
        width=10,
        command=self.close_app,
    ).pack(side=tk.RIGHT, padx=2)

    self.last_rendered_img = None

  def play_ecosystem_sound(self, event_type, value):
    """Generates procedural ecosystem audio feedback."""
    try:
      duration = 0.05
      sample_rate = 22050
      t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)

      if event_type == "spark":
        freq = 400 + (value * 200)
        audio = 0.1 * np.sin(2 * np.pi * freq * t)
      elif event_type == "frost":
        freq = 90 + (value * 50)
        audio = 0.15 * np.sin(2 * np.pi * freq * t)
      else:  # Neutralization / Steam pop
        freq = 600 - (value * 200)
        audio = 0.2 * np.random.uniform(-1, 1, len(t)) * np.sin(2 * np.pi * freq * t)

      fade = np.linspace(1, 0, len(audio))
      audio = (audio * fade * 32767).astype(np.int16)
      pygame.mixer.Sound(buffer=audio).play()
    except Exception:
      pass

  def read_serial_stream(self):
    buffer = []
    collecting = False

    while self.running:
      try:
        line = self.ser.readline().decode("utf-8", errors="ignore").strip()

        if line == "FRAME_START":
          buffer = []
          collecting = True
          continue

        elif line == "FRAME_END" and collecting:
          collecting = False
          if len(buffer) == 768:
            data = np.array(buffer, dtype=np.float32).reshape(24, 32)
            data = np.flipud(data)

            if self.frame_queue.full():
              try:
                self.frame_queue.get_nowait()
              except Empty:
                pass
            self.frame_queue.put(data)
          continue

        if collecting:
          parts = line.split(",")
          for p in parts:
            try:
              buffer.append(float(p))
            except ValueError:
              pass
      except Exception:
        break

  def update_gui(self):
    try:
      data = self.frame_queue.get_nowait()

      min_val, max_val = np.min(data), np.max(data)
      if max_val == min_val:
        max_val = min_val + 0.1
      centre_val = data[11, 15]

      self.lbl_max.config(text=f"{max_val:.1f} C")
      self.lbl_min.config(text=f"{min_val:.1f} C")
      self.lbl_centre.config(text=f"{centre_val:.1f} C")

      norm_data = np.clip((data - min_val) / (max_val - min_val), 0, 1)
      img_8bit = (norm_data * 255).astype(np.uint8)
      enlarged = cv2.resize(
          img_8bit, (480, 360), interpolation=cv2.INTER_CUBIC
      )
      active_cmap = COLORMAPS[self.current_cmap_idx][1]
      colored = cv2.applyColorMap(enlarged, active_cmap)

      # --- Micro-Climate Ecosystem Simulation Engine ---
      if self.ecosystem_active:
        # Compute flow field gradients from thermal data for convection winds
        grad_y, grad_x = np.gradient(norm_data)

        hot_indices = np.argwhere(norm_data > 0.65)
        cold_indices = np.argwhere(norm_data < 0.35)

        # Spawn ecosystem lifeforms
        if len(self.particles) < 250:
          if len(hot_indices) > 0 and random.random() < 0.6:
            r_idx = random.randint(0, len(hot_indices) - 1)
            r, c = hot_indices[r_idx]
            factor = np.clip((norm_data[r, c] - 0.65) / 0.35, 0.0, 1.0)
            self.particles.append({
                "type": "spark",
                "x": c * (480 / 32.0),
                "y": r * (360 / 24.0),
                "vx": random.uniform(-0.5, 0.5),
                "vy": -1.0 - (factor * 4.0),
                "radius": int(2 + factor * 5),
                "life": int(30 + factor * 40),
                "max_life": int(30 + factor * 40),
            })
            self.play_ecosystem_sound("spark", factor)

          if len(cold_indices) > 0 and random.random() < 0.6:
            r_idx = random.randint(0, len(cold_indices) - 1)
            r, c = cold_indices[r_idx]
            factor = np.clip((0.35 - norm_data[r, c]) / 0.35, 0.0, 1.0)
            self.particles.append({
                "type": "frost",
                "x": c * (480 / 32.0),
                "y": r * (360 / 24.0),
                "vx": random.uniform(-0.5, 0.5),
                "vy": 0.8 + (factor * 3.0),
                "radius": int(2 + factor * 4),
                "life": int(35 + factor * 40),
                "max_life": int(35 + factor * 40),
            })
            self.play_ecosystem_sound("frost", factor)

        # Update physics with convection flow
        surviving_particles = []
        for p in self.particles:
          # Map particle position back to 24x32 grid to sample local wind currents
          grid_c = int(np.clip(p["x"] / (480 / 32.0), 0, 31))
          grid_r = int(np.clip(p["y"] / (360 / 24.0), 0, 23))

          # Apply thermal wind forces
          wind_x = grad_x[grid_r, grid_c] * 2.0
          wind_y = grad_y[grid_r, grid_c] * 2.0

          p["vx"] = p["vx"] * 0.95 + wind_x * 0.1
          p["vy"] = p["vy"] * 0.95 + wind_y * 0.1

          p["x"] += p["vx"]
          p["y"] += p["vy"]
          p["life"] -= 1

          if p["life"] > 0 and 0 <= p["x"] < 480 and 0 <= p["y"] < 360:
            surviving_particles.append(p)
            fade = p["life"] / p["max_life"]

            if p["type"] == "spark":
              color = (int(255 * fade), int(180 * fade), 255)
            else:
              color = (255, int(200 * fade), int(100 * fade))

            cv2.circle(
                colored,
                (int(p["x"]), int(p["y"])),
                max(1, int(p["radius"] * fade)),
                color,
                -1,
            )

        self.particles = surviving_particles

        cv2.putText(
            colored,
            "ECOSYSTEM: CONVECTION ACTIVE",
            (20, 340),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            2,
        )

      rgb_img = cv2.cvtColor(colored, cv2.COLOR_BGR2RGB)
      pil_img = Image.fromarray(rgb_img)
      self.last_rendered_img = pil_img

      tk_img = ImageTk.PhotoImage(image=pil_img)
      self.canvas_label.config(image=tk_img)
      self.canvas_label.image = tk_img

    except Empty:
      pass

    if self.running:
      self.root.after(20, self.update_gui)

  def toggle_ecosystem(self):
    self.ecosystem_active = not self.ecosystem_active
    if self.ecosystem_active:
      self.btn_ecosystem.config(text="Ecosystem: ON", bg="#9c27b0")
      self.lbl_cmap.config(text="Map:\nMicro-Climate")
      self.particles = []
    else:
      self.btn_ecosystem.config(text="Ecosystem: OFF", bg="#607D8B")
      cmap_name = COLORMAPS[self.current_cmap_idx][0]
      self.lbl_cmap.config(text=f"Map:\n{cmap_name}")

  def cycle_colormap(self):
    self.current_cmap_idx = (self.current_cmap_idx + 1) % len(COLORMAPS)
    cmap_name = COLORMAPS[self.current_cmap_idx][0]
    if not self.ecosystem_active:
      self.lbl_cmap.config(text=f"Map:\n{cmap_name}")

  def save_snapshot(self, prefix="thermal_snapshot"):
    if self.last_rendered_img:
      filename = f"{prefix}_{int(time.time())}.png"
      self.last_rendered_img.save(filename)
      print(f"Saved: {filename}")
      return filename
    else:
      messagebox.showwarning(
          "Warning", "No active frame available to save yet."
      )
      return None

  def start_delayed_snapshot(self):
    self.countdown_val = 3
    self.run_countdown(is_burst=False)

  def start_burst_snapshot(self):
    self.countdown_val = 3
    self.burst_count_remaining = 5
    self.run_countdown(is_burst=True)

  def run_countdown(self, is_burst):
    if self.countdown_val > 0:
      self.lbl_cmap.config(text=f"Snap in:\n{self.countdown_val}s...")
      self.countdown_val -= 1
      self.root.after(1000, lambda: self.run_countdown(is_burst))
    else:
      if not self.ecosystem_active:
        cmap_name = COLORMAPS[self.current_cmap_idx][0]
        self.lbl_cmap.config(text=f"Map:\n{cmap_name}")
      else:
        self.lbl_cmap.config(text="Map:\nMicro-Climate")

      if is_burst:
        self.execute_burst_shot()
      else:
        fname = self.save_snapshot()
        if fname:
          messagebox.showinfo(
              "Snapshot Saved", f"Successfully saved snapshot as:\n{fname}"
          )

  def execute_burst_shot(self):
    if self.burst_count_remaining > 0:
      burst_idx = 6 - self.burst_count_remaining
      self.save_snapshot(prefix=f"thermal_burst_{burst_idx}")
      self.burst_count_remaining -= 1

      if self.burst_count_remaining > 0:
        self.lbl_cmap.config(text=f"Bursting:\n{self.burst_count_remaining} left")
        self.root.after(1000, self.execute_burst_shot)
      else:
        if not self.ecosystem_active:
          cmap_name = COLORMAPS[self.current_cmap_idx][0]
          self.lbl_cmap.config(text=f"Map:\n{cmap_name}")
        else:
          self.lbl_cmap.config(text="Map:\nMicro-Climate")
        messagebox.showinfo(
            "Burst Complete", "Successfully captured 5 burst snapshots (1s apart)."
        )

  def close_app(self):
    self.running = False
    if self.ser and self.ser.is_open:
      self.ser.close()
    self.root.destroy()


if __name__ == "__main__":
  root = tk.Tk()
  app = ThermalStreamApp(root)
  root.protocol("WM_DELETE_WINDOW", app.close_app)
  root.mainloop()