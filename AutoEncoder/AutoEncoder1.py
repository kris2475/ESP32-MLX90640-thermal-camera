from collections import deque
from queue import Empty, Queue
from threading import Thread
import time
import cv2
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np
from PIL import Image, ImageGrab, ImageTk
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import messagebox, ttk
import torch
import torch.nn as nn
import torch.optim as optim

matplotlib.use("TkAgg")

BAUD = 500000

COLORMAPS = [
    ("Jet (Ironbow-like)", cv2.COLORMAP_JET),
    ("Turbo", cv2.COLORMAP_TURBO),
    ("Inferno", cv2.COLORMAP_INFERNO),
    ("Magma", cv2.COLORMAP_MAGMA),
]


class ThermalAutoencoder(nn.Module):

  def __init__(self):
    super().__init__()
    # Compresses 768 float inputs (24x32 grid) down to an 8-dim latent bottleneck
    self.encoder = nn.Sequential(
        nn.Linear(768, 128),
        nn.ReLU(),
        nn.Linear(128, 32),
        nn.ReLU(),
        nn.Linear(32, 8),
    )
    self.decoder = nn.Sequential(
        nn.Linear(8, 32),
        nn.ReLU(),
        nn.Linear(32, 128),
        nn.ReLU(),
        nn.Linear(128, 768),
        nn.Sigmoid(),
    )

  def forward(self, x):
    latent = self.encoder(x)
    reconstructed = self.decoder(latent)
    return reconstructed, latent


class ThermalMLProApp:

  def __init__(self, root):
    self.root = root
    self.root.title(
        "ESP32 Thermal Stream - Pro ML Autoencoder & Anomaly Suite"
    )
    self.root.geometry("1100x750")
    self.root.resizable(False, False)

    self.ser = None
    self.running = False
    self.frame_queue = Queue(maxsize=2)
    self.current_cmap_idx = 0

    self.pipeline_mode = "IDLE"
    self.train_iterations = 0
    self.anomaly_threshold = 0.015
    self.loss_history = deque(maxlen=100)

    self.autoencoder = ThermalAutoencoder()
    self.optimizer = optim.Adam(self.autoencoder.parameters(), lr=0.005)
    self.criterion = nn.MSELoss()

    # Static model metrics
    self.total_params = sum(
        p.numel() for p in self.autoencoder.parameters() if p.requires_grad
    )
    self.compression_ratio = 768 / 8  # Input size / Latent size

    self.current_loss = 0.0
    self.latent_vector = np.zeros(8)
    self.latent_norm = 0.0
    self.inference_latency_ms = 0.0

    # --- COM Port Selection Screen ---
    self.setup_frame = tk.Frame(root, padx=20, pady=20)
    self.setup_frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        self.setup_frame,
        text="Select ESP32 COM Port:",
        font=("Arial", 12, "bold"),
    ).pack(pady=15)

    self.port_combobox = ttk.Combobox(
        self.setup_frame, state="readonly", width=30, font=("Arial", 10)
    )
    self.port_combobox.pack(pady=5)
    self.refresh_ports()

    tk.Button(
        self.setup_frame,
        text="Connect & Initialize Dashboard",
        bg="#2196F3",
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
      messagebox.showerror("Error", "Please select a valid serial port.")
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
    # --- TOP SECTION: Visual Comparison & Graph ---
    top_frame = tk.Frame(self.root)
    top_frame.pack(fill=tk.X, padx=15, pady=10)

    # Original Stream Box
    orig_box = tk.LabelFrame(
        top_frame, text="Original Input (24x32 Grid)", font=("Arial", 9, "bold")
    )
    orig_box.pack(side=tk.LEFT, padx=5)
    orig_box.pack_propagate(False)
    orig_box.config(width=340, height=270)
    self.canvas_original = tk.Label(orig_box, bg="black")
    self.canvas_original.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # Reconstructed Stream Box
    recon_box = tk.LabelFrame(
        top_frame,
        text="Reconstructed (8D Latent Bottleneck)",
        font=("Arial", 9, "bold"),
    )
    recon_box.pack(side=tk.LEFT, padx=5)
    recon_box.pack_propagate(False)
    recon_box.config(width=340, height=270)
    self.canvas_reconstructed = tk.Label(recon_box, bg="black")
    self.canvas_reconstructed.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # Live Loss Graph Box (Matplotlib)
    graph_box = tk.LabelFrame(
        top_frame, text="Live Reconstruction Loss (MSE)", font=("Arial", 9, "bold")
    )
    graph_box.pack(side=tk.LEFT, padx=5)
    graph_box.pack_propagate(False)
    graph_box.config(width=360, height=270)

    self.fig, self.ax = plt.subplots(figsize=(3.4, 2.3))
    self.fig.patch.set_facecolor("#f0f0f0")
    self.ax.set_facecolor("white")
    self.ax.tick_params(axis="both", which="major", labelsize=8)
    self.line_loss, = self.ax.plot([], [], "b-", lw=1.5)
    self.ax.set_xlim(0, 100)
    self.ax.set_ylim(0, 0.1)
    self.ax.grid(True, linestyle="--", alpha=0.5)
    self.fig.tight_layout()

    self.canvas_graph = FigureCanvasTkAgg(self.fig, master=graph_box)
    self.canvas_graph.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # --- MIDDLE SECTION: Telemetry & Advanced Model Info ---
    mid_frame = tk.Frame(
        self.root, bg="#f9f9f9", bd=1, relief=tk.SOLID, padx=10, pady=10
    )
    mid_frame.pack(fill=tk.X, padx=20, pady=5)

    # Column 1: Pipeline & Training Telemetry
    col1 = tk.Frame(mid_frame, bg="#f9f9f9")
    col1.pack(side=tk.LEFT, expand=True, fill=tk.X)

    self.lbl_mode = tk.Label(
        col1,
        text="Pipeline State: IDLE",
        font=("Arial", 10, "bold"),
        fg="blue",
        bg="#f9f9f9",
    )
    self.lbl_mode.pack(anchor="w", pady=1)
    self.lbl_loss = tk.Label(
        col1, text="Current MSE Loss: 0.00000", font=("Arial", 9), bg="#f9f9f9"
    )
    self.lbl_loss.pack(anchor="w", pady=1)
    self.lbl_iters = tk.Label(
        col1, text="Training Iterations: 0", font=("Arial", 9), bg="#f9f9f9"
    )
    self.lbl_iters.pack(anchor="w", pady=1)
    self.lbl_alert = tk.Label(
        col1,
        text="SYSTEM STATUS: NORMAL",
        font=("Arial", 9, "bold"),
        fg="green",
        bg="#f9f9f9",
    )
    self.lbl_alert.pack(anchor="w", pady=1)

    # Column 2: Architecture & Latency Metrics
    col2 = tk.Frame(mid_frame, bg="#f9f9f9")
    col2.pack(side=tk.LEFT, expand=True, fill=tk.X)

    tk.Label(
        col2,
        text=f"Model Architecture: Linear Autoencoder",
        font=("Arial", 9, "bold"),
        bg="#f9f9f9",
    ).pack(anchor="w", pady=1)
    self.lbl_params = tk.Label(
        col2,
        text=f"Trainable Parameters: {self.total_params:,} ({self.compression_ratio:.0f}:1 Ratio)",
        font=("Arial", 9),
        bg="#f9f9f9",
    )
    self.lbl_params.pack(anchor="w", pady=1)
    self.lbl_latency = tk.Label(
        col2,
        text="Forward Pass Latency: 0.00 ms",
        font=("Arial", 9),
        bg="#f9f9f9",
    )
    self.lbl_latency.pack(anchor="w", pady=1)
    self.lbl_norm = tk.Label(
        col2,
        text="Latent L2 Norm Magnitude: 0.00",
        font=("Arial", 9),
        bg="#f9f9f9",
    )
    self.lbl_norm.pack(anchor="w", pady=1)

    # Column 3: Latent Vector Values
    col3 = tk.Frame(mid_frame, bg="#f9f9f9")
    col3.pack(side=tk.LEFT, expand=True, fill=tk.X)

    tk.Label(
        col3,
        text="8-Dim Latent Bottleneck Vector:",
        font=("Arial", 9, "bold"),
        bg="#f9f9f9",
    ).pack(anchor="w")
    self.lbl_latent = tk.Label(
        col3, text="[--]", font=("Consolas", 8), fg="#333", bg="#f9f9f9"
    )
    self.lbl_latent.pack(anchor="w", pady=5)

    # --- BOTTOM SECTION: Controls & Action Buttons ---
    btn_frame = tk.Frame(self.root, pady=10)
    btn_frame.pack(fill=tk.X, padx=20)

    self.btn_train = tk.Button(
        btn_frame,
        text="1. Train Baseline",
        bg="#4CAF50",
        fg="white",
        font=("Arial", 9, "bold"),
        width=15,
        command=self.set_mode_training,
    )
    self.btn_train.pack(side=tk.LEFT, padx=4)

    self.btn_inference = tk.Button(
        btn_frame,
        text="2. Run Inference",
        bg="#9C27B0",
        fg="white",
        font=("Arial", 9, "bold"),
        width=15,
        command=self.set_mode_inference,
    )
    self.btn_inference.pack(side=tk.LEFT, padx=4)

    tk.Button(
        btn_frame,
        text="Reset Model",
        bg="#FF5722",
        fg="white",
        font=("Arial", 9, "bold"),
        width=12,
        command=self.reset_model,
    ).pack(side=tk.LEFT, padx=4)

    tk.Button(
        btn_frame,
        text="Colormap",
        bg="#FF9800",
        fg="white",
        font=("Arial", 9, "bold"),
        width=11,
        command=self.cycle_colormap,
    ).pack(side=tk.LEFT, padx=4)

    tk.Button(
        btn_frame,
        text="Snapshot Dash",
        bg="#2196F3",
        fg="white",
        font=("Arial", 9, "bold"),
        width=13,
        command=self.save_snapshot,
    ).pack(side=tk.LEFT, padx=4)

    tk.Button(
        btn_frame,
        text="Exit",
        bg="#78909C",
        fg="white",
        font=("Arial", 9, "bold"),
        width=8,
        command=self.close_app,
    ).pack(side=tk.RIGHT, padx=4)

  def set_mode_training(self):
    self.pipeline_mode = "TRAINING"
    self.lbl_mode.config(
        text="Pipeline State: TRAINING (Adapting Baseline)", fg="green"
    )

  def set_mode_inference(self):
    self.pipeline_mode = "INFERENCE"
    self.lbl_mode.config(
        text="Pipeline State: INFERENCE (Detecting Anomalies)", fg="purple"
    )

  def reset_model(self):
    self.autoencoder = ThermalAutoencoder()
    self.optimizer = optim.Adam(self.autoencoder.parameters(), lr=0.005)
    self.train_iterations = 0
    self.loss_history.clear()
    self.pipeline_mode = "IDLE"
    self.lbl_mode.config(text="Pipeline State: IDLE (Model Reset)", fg="blue")
    messagebox.showinfo(
        "Model Reset",
        "Autoencoder weights have been re-initialized from scratch.",
    )

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

      norm_data = np.clip((data - min_val) / (max_val - min_val), 0, 1)
      flat_tensor = torch.tensor(
          norm_data.flatten(), dtype=torch.float32
      ).unsqueeze(0)

      # --- Execute Model Pipeline with Latency Timing ---
      start_time = time.perf_counter()

      if self.pipeline_mode == "TRAINING":
        self.autoencoder.train()
        self.optimizer.zero_grad()
        reconstructed_flat, latent_tensor = self.autoencoder(flat_tensor)
        loss = self.criterion(reconstructed_flat, flat_tensor)
        loss.backward()
        self.optimizer.step()

        self.current_loss = loss.item()
        self.latent_vector = latent_tensor.detach().numpy().flatten()
        self.train_iterations += 1
        self.loss_history.append(self.current_loss)
        self.lbl_alert.config(text="SYSTEM STATUS: LEARNING", fg="green")

      elif self.pipeline_mode == "INFERENCE":
        self.autoencoder.eval()
        with torch.no_grad():
          reconstructed_flat, latent_tensor = self.autoencoder(flat_tensor)
          loss = self.criterion(reconstructed_flat, flat_tensor)

        self.current_loss = loss.item()
        self.latent_vector = latent_tensor.numpy().flatten()
        self.loss_history.append(self.current_loss)

        if self.current_loss > self.anomaly_threshold:
          self.lbl_alert.config(
              text="⚠️ ANOMALY DETECTED (High MSE Loss)", fg="red"
          )
        else:
          self.lbl_alert.config(text="SYSTEM STATUS: STABLE / NORMAL", fg="green")

      else:  # IDLE
        with torch.no_grad():
          reconstructed_flat, latent_tensor = self.autoencoder(flat_tensor)
        self.current_loss = 0.0
        self.latent_vector = latent_tensor.numpy().flatten()

      end_time = time.perf_counter()
      self.inference_latency_ms = (end_time - start_time) * 1000.0
      self.latent_norm = np.linalg.norm(self.latent_vector)

      # --- Update Telemetry UI Text ---
      self.lbl_loss.config(text=f"Current MSE Loss: {self.current_loss:.5f}")
      self.lbl_iters.config(text=f"Training Iterations: {self.train_iterations}")
      self.lbl_latency.config(
          text=f"Forward Pass Latency: {self.inference_latency_ms:.2f} ms"
      )
      self.lbl_norm.config(
          text=f"Latent L2 Norm Magnitude: {self.latent_norm:.2f}"
      )

      latent_str = ", ".join([f"{val:.2f}" for val in self.latent_vector])
      self.lbl_latent.config(text=f"[{latent_str}]")

      # --- Update Live Graph ---
      if len(self.loss_history) > 0:
        y_data = list(self.loss_history)
        x_data = list(range(len(y_data)))
        self.line_loss.set_data(x_data, y_data)
        self.ax.set_xlim(0, max(100, len(x_data)))
        max_y = max(y_data) if max(y_data) > 0.05 else 0.05
        self.ax.set_ylim(0, max_y * 1.2)
        self.canvas_graph.draw()

      # --- Render Images ---
      img_8bit = (norm_data * 255).astype(np.uint8)
      enlarged_orig = cv2.resize(
          img_8bit, (320, 240), interpolation=cv2.INTER_CUBIC
      )
      active_cmap = COLORMAPS[self.current_cmap_idx][1]
      colored_orig = cv2.applyColorMap(enlarged_orig, active_cmap)

      recon_grid = reconstructed_flat.detach().numpy().reshape(24, 32)
      recon_8bit = (np.clip(recon_grid, 0, 1) * 255).astype(np.uint8)
      enlarged_recon = cv2.resize(
          recon_8bit, (320, 240), interpolation=cv2.INTER_CUBIC
      )
      colored_recon = cv2.applyColorMap(enlarged_recon, active_cmap)

      rgb_orig = cv2.cvtColor(colored_orig, cv2.COLOR_BGR2RGB)
      pil_orig = Image.fromarray(rgb_orig)
      tk_orig = ImageTk.PhotoImage(image=pil_orig)
      self.canvas_original.config(image=tk_orig)
      self.canvas_original.image = tk_orig

      rgb_recon = cv2.cvtColor(colored_recon, cv2.COLOR_BGR2RGB)
      pil_recon = Image.fromarray(rgb_recon)
      tk_recon = ImageTk.PhotoImage(image=pil_recon)
      self.canvas_reconstructed.config(image=tk_recon)
      self.canvas_reconstructed.image = tk_recon

    except Empty:
      pass

    if self.running:
      self.root.after(20, self.update_gui)

  def cycle_colormap(self):
    self.current_cmap_idx = (self.current_cmap_idx + 1) % len(COLORMAPS)

  def save_snapshot(self):
    try:
      self.root.update_idletasks()
      x = self.root.winfo_rootx()
      y = self.root.winfo_rooty()
      w = self.root.winfo_width()
      h = self.root.winfo_height()

      timestamp = int(time.time())
      filename = f"thermal_dashboard_snapshot_{timestamp}.png"

      # Grab the exact boundaries of the application window
      screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
      screenshot.save(filename)
      messagebox.showinfo(
          "Snapshot Saved", f"Entire dashboard saved successfully as:\n{filename}"
      )
    except Exception as e:
      messagebox.showerror(
          "Snapshot Error", f"Failed to capture dashboard window: {e}"
      )

  def close_app(self):
    self.running = False
    if self.ser and self.ser.is_open:
      self.ser.close()
    self.root.destroy()


if __name__ == "__main__":
  root = tk.Tk()
  app = ThermalMLProApp(root)
  root.protocol("WM_DELETE_WINDOW", app.close_app)
  root.mainloop()