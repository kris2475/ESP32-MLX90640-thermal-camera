from threading import Thread
import cv2
import numpy as np
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import messagebox, ttk

BAUD = 500000


class ThermalStreamApp:

  def __init__(self, root):
    self.root = root
    self.root.title("Select Serial Port - Thermal Stream")
    self.root.geometry("380x180")
    self.root.resizable(False, False)

    self.ser = None
    self.running = False

    # UI Label
    lbl = tk.Label(
        root,
        text="Choose ESP32 COM Port:",
        font=("Arial", 11, "bold"),
    )
    lbl.pack(pady=15)

    # Drop-down (Combobox) for COM ports
    self.port_combobox = ttk.Combobox(
        root, state="readonly", width=30, font=("Arial", 10)
    )
    self.port_combobox.pack(pady=5)
    self.refresh_ports()

    # Connect Button
    self.btn_connect = tk.Button(
        root,
        text="Connect & Launch Viewer",
        bg="#4CAF50",
        fg="white",
        font=("Arial", 10, "bold"),
        command=self.start_stream,
    )
    self.btn_connect.pack(pady=15)

  def refresh_ports(self):
    ports = [port.device for port in serial.tools.list_ports.comports()]
    if not ports:
      ports = ["No ports found"]
    self.port_combobox["values"] = ports
    self.port_combobox.current(0)

  def start_stream(self):
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

    self.running = True
    # Close configuration window and start viewing loop
    self.root.destroy()
    self.run_viewer()

  def run_viewer(self):
    print("Listening for thermal stream... Press 'q' to quit, 's' to save snapshot.")
    buffer = []
    collecting = False

    try:
      while self.running:
        line = self.ser.readline().decode("utf-8", errors="ignore").strip()

        if line == "FRAME_START":
          buffer = []
          collecting = True
          continue

        elif line == "FRAME_END" and collecting:
          collecting = False
          if len(buffer) == 768:
            data = np.array(buffer, dtype=np.float32).reshape(24, 32)
            
            # Flip vertically to correct upside-down orientation
            data = np.flipud(data)

            min_val, max_val = np.min(data), np.max(data)
            if max_val == min_val:
              max_val = min_val + 0.1

            norm_data = np.clip((data - min_val) / (max_val - min_val), 0, 1)
            img_8bit = (norm_data * 255).astype(np.uint8)

            enlarged = cv2.resize(
                img_8bit, (480, 360), interpolation=cv2.INTER_CUBIC
            )
            colored = cv2.applyColorMap(enlarged, cv2.COLORMAP_JET)

            cv2.putText(
                colored,
                f"MAX: {max_val:.1f} C",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 0, 255),
                2,
            )
            cv2.putText(
                colored,
                f"MIN: {min_val:.1f} C",
                (20, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 0, 0),
                2,
            )

            cv2.imshow("ESP32 Thermal Reconstitution", colored)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
              break
            elif key == ord("s"):
              cv2.imwrite("thermal_snapshot.png", colored)
              print("Snapshot saved as thermal_snapshot.png")

          continue

        if collecting:
          parts = line.split(",")
          for p in parts:
            try:
              buffer.append(float(p))
            except ValueError:
              pass

    except Exception as e:
      print(f"Stream error: {e}")
    finally:
      if self.ser and self.ser.is_open:
        self.ser.close()
      cv2.destroyAllWindows()


if __name__ == "__main__":
  root = tk.Tk()
  app = ThermalStreamApp(root)
  root.mainloop()