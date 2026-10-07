from queue import Empty, Queue
import random
from threading import Thread
import time
import cv2
import numpy as np
from PIL import Image, ImageTk
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import messagebox, ttk

BAUD = 500000

# Available colormaps for regular viewing
COLORMAPS = [
    ("Jet (Ironbow-like)", cv2.COLORMAP_JET),
    ("Turbo", cv2.COLORMAP_TURBO),
    ("Inferno", cv2.COLORMAP_INFERNO),
    ("Magma", cv2.COLORMAP_MAGMA),
]


class ThermalStreamApp:

  def __init__(self, root):
    self.root = root
    self.root.title("ESP32 Thermal Stream Viewer & Frost/Embers")
    self.root.geometry("520x450")
    self.root.resizable(False, False)

    self.ser = None
    self.running = False
    self.frame_queue = Queue(maxsize=2)
    self.current_cmap_idx = 0
    self.countdown_val = 0
    self.burst_count_remaining = 0

    # Particle System State
    self.particle_mode_active = False
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

    # Destroy setup frame and build main dashboard
    self.setup_frame.destroy()
    self.build_dashboard()

    self.running = True
    # Start background serial reader thread
    self.reader_thread = Thread(target=self.read_serial_stream, daemon=True)
    self.reader_thread.start()

    # Start Tkinter GUI update loop
    self.update_gui()

  def build_dashboard(self):
    self.root.geometry("640x550")

    # Image Display Panel (Left)
    self.canvas_label = tk.Label(self.root, bg="black")
    self.canvas_label.place(x=20, y=20, width=480, height=360)

    # Telemetry & Control Panel (Right)
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

    # Control Push Buttons Frame (Bottom)
    btn_frame = tk.Frame(self.root, pady=10)
    btn_frame.place(x=20, y=390, width=600, height=130)

    # Row 1 of buttons
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

    # Row 2 of buttons (Colormap, Particle Mode toggle, and Exit)
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

    self.btn_particle = tk.Button(
        row2,
        text="Particle Mode: OFF",
        bg="#607D8B",
        fg="white",
        font=("Arial", 9, "bold"),
        width=16,
        command=self.toggle_particle_mode,
    )
    self.btn_particle.pack(side=tk.LEFT, padx=5)

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
            data = np.flipud(data)  # Correct orientation

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

      # Update sidebar telemetry labels
      self.lbl_max.config(text=f"{max_val:.1f} C")
      self.lbl_min.config(text=f"{min_val:.1f} C")
      self.lbl_centre.config(text=f"{centre_val:.1f} C")

      # Standard frame rendering
      norm_data = np.clip((data - min_val) / (max_val - min_val), 0, 1)
      img_8bit = (norm_data * 255).astype(np.uint8)
      enlarged = cv2.resize(
          img_8bit, (480, 360), interpolation=cv2.INTER_CUBIC
      )
      active_cmap = COLORMAPS[self.current_cmap_idx][1]
      colored = cv2.applyColorMap(enlarged, active_cmap)

      # Bi-directional Weather Simulation Layer (Embers & Frost)
      if self.particle_mode_active:
        hot_indices = np.argwhere(norm_data > 0.65)
        cold_indices = np.argwhere(norm_data < 0.35)

        if len(self.particles) < 300:
          # Spawn Hot Embers (Rising)
          if len(hot_indices) > 0:
            for _ in range(2):
              r_idx = random.randint(0, len(hot_indices) - 1)
              r, c = hot_indices[r_idx]
              intensity = norm_data[r, c]
              factor = np.clip((intensity - 0.65) / 0.35, 0.0, 1.0)

              px = c * (480 / 32.0) + random.uniform(-5, 5)
              py = r * (360 / 24.0) + random.uniform(-5, 5)
              vx = random.uniform(-0.8, 0.8)
              vy = -0.5 - (factor * 7.0)  # Rising fast
              radius = int(1 + (factor**1.5) * 10)
              life = int(20 + (factor * 40))

              self.particles.append({
                  "type": "hot",
                  "x": px,
                  "y": py,
                  "vx": vx,
                  "vy": vy,
                  "radius": radius,
                  "life": life,
                  "max_life": life,
                  "factor": factor,
              })

          # Spawn Cold Frost (Sinking)
          if len(cold_indices) > 0:
            for _ in range(2):
              r_idx = random.randint(0, len(cold_indices) - 1)
              r, c = cold_indices[r_idx]
              coldness = 1.0 - norm_data[r, c]
              factor = np.clip((norm_data[r, c] - 0.0) / 0.35, 0.0, 1.0)
              # inverted factor so colder = heavier drop
              drop_factor = 1.0 - factor

              px = c * (480 / 32.0) + random.uniform(-5, 5)
              py = r * (360 / 24.0) + random.uniform(-5, 5)
              vx = random.uniform(-0.4, 0.4)
              vy = 0.5 + (drop_factor * 5.0)  # Sinking down
              radius = int(1 + (drop_factor * 8))
              life = int(25 + (drop_factor * 45))

              self.particles.append({
                  "type": "cold",
                  "x": px,
                  "y": py,
                  "vx": vx,
                  "vy": vy,
                  "radius": radius,
                  "life": life,
                  "max_life": life,
                  "factor": drop_factor,
              })

        # Update and draw particles
        surviving_particles = []
        for p in self.particles:
          p["x"] += p["vx"]
          p["y"] += p["vy"]
          p["life"] -= 1

          if p["life"] > 0 and 0 <= p["x"] < 480 and 0 <= p["y"] < 360:
            surviving_particles.append(p)
            fade_ratio = p["life"] / p["max_life"]

            if p["type"] == "hot":
              # Fiery white/orange core for heat
              color = (
                  int(255 * fade_ratio),
                  int(200 * fade_ratio),
                  255,
              )  # BGR
            else:
              # Icy cyan/blue for cold frost drips
              color = (
                  255,
                  int(220 * fade_ratio),
                  int(100 * fade_ratio),
              )  # BGR bright blue/cyan

            current_radius = max(1, int(p["radius"] * fade_ratio))
            cv2.circle(
                colored,
                (int(p["x"]), int(p["y"])),
                current_radius,
                color,
                -1,
            )

        self.particles = surviving_particles

        # Overlay mode badge
        cv2.putText(
            colored,
            "WEATHER: EMBERS & FROST",
            (20, 340),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 0),
            2,
        )

      # Convert OpenCV BGR to RGB for PIL/Tkinter
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

  def toggle_particle_mode(self):
    self.particle_mode_active = not self.particle_mode_active
    if self.particle_mode_active:
      self.btn_particle.config(text="Particle Mode: ON", bg="#9c27b0")
      self.lbl_cmap.config(text="Map:\nEmbers & Frost")
      self.particles = []
    else:
      self.btn_particle.config(text="Particle Mode: OFF", bg="#607D8B")
      cmap_name = COLORMAPS[self.current_cmap_idx][0]
      self.lbl_cmap.config(text=f"Map:\n{cmap_name}")

  def cycle_colormap(self):
    self.current_cmap_idx = (self.current_cmap_idx + 1) % len(COLORMAPS)
    cmap_name = COLORMAPS[self.current_cmap_idx][0]
    if not self.particle_mode_active:
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
      if not self.particle_mode_active:
        cmap_name = COLORMAPS[self.current_cmap_idx][0]
        self.lbl_cmap.config(text=f"Map:\n{cmap_name}")
      else:
        self.lbl_cmap.config(text="Map:\nEmbers & Frost")

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
        if not self.particle_mode_active:
          cmap_name = COLORMAPS[self.current_cmap_idx][0]
          self.lbl_cmap.config(text=f"Map:\n{cmap_name}")
        else:
          self.lbl_cmap.config(text="Map:\nEmbers & Frost")
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