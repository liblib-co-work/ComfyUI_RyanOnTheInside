import torch
import numpy as np
import cv2
from abc import ABC, abstractmethod
from comfy.utils import ProgressBar
from ... import RyanOnTheInside

class BaseAudioProcessor:
    def __init__(self, audio, num_frames, height, width, frame_rate):
        """
        Base class to process audio data.

        Parameters:
        - audio: dict with 'waveform' and 'sample_rate'.
        - num_frames: int, total number of frames to process.
        - height: int, height of the output image.
        - width: int, width of the output image.
        - frame_rate: float, frame rate for processing.
        """
        # Convert waveform tensor to mono numpy array
        self.audio = audio['waveform'].squeeze(0).mean(axis=0).cpu().numpy()
        self.sample_rate = audio['sample_rate']
        self.num_frames = num_frames
        self.height = height
        self.width = width
        self.frame_rate = frame_rate

        self.audio_duration = len(self.audio) / self.sample_rate
        self.frame_duration = 1 / self.frame_rate if self.frame_rate > 0 else self.audio_duration / self.num_frames
        self.progress_bar = None

    def start_progress(self, total_steps, desc="Processing"):
        self.progress_bar = ProgressBar(total_steps)

    def update_progress(self):
        if self.progress_bar:
            self.progress_bar.update(1)

    def end_progress(self):
        self.progress_bar = None

    def _normalize(self, data):
        return (data - data.min()) / (data.max() - data.min())

    def _enhance_contrast(self, data, power=0.3):
        return np.power(data, power)

    def _resize(self, data, new_width, new_height):
        return cv2.resize(data, (new_width, new_height), interpolation=cv2.INTER_LINEAR)

    def _get_audio_frame(self, frame_index):
        start_time = frame_index * self.frame_duration
        end_time = (frame_index + 1) * self.frame_duration
        start_sample = int(start_time * self.sample_rate)
        end_sample = int(end_time * self.sample_rate)
        return self.audio[start_sample:end_sample]

class FlexAudioVisualizerBase(RyanOnTheInside, ABC):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "frame_rate": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 240.0, "step": 1.0}),
                "screen_width": ("INT", {"default": 800, "min": 100, "max": 1920, "step": 1}),
                "screen_height": ("INT", {"default": 600, "min": 100, "max": 1080, "step": 1}),
                "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "feature_param": (cls.get_modifiable_params(), {"default": cls.get_modifiable_params()[0]}),
                "feature_mode": (["relative", "absolute"], {"default": "relative"}),
            },
            "optional": {
                "opt_feature": ("FEATURE",)
            }
        }

    CATEGORY = "RyanOnTheInside/FlexAudioVisualizer"
    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "apply_effect"

    def __init__(self):
        self.progress_bar = None

    def start_progress(self, total_steps, desc="Processing"):
        self.progress_bar = ProgressBar(total_steps)

    def update_progress(self):
        if self.progress_bar:
            self.progress_bar.update(1)

    def end_progress(self):
        self.progress_bar = None

    @classmethod
    @abstractmethod
    def get_modifiable_params(cls):
        """Return a list of parameter names that can be modulated."""
        pass

    def modulate_param(self, param_name, param_value, feature_value, strength, mode):
        if mode == "relative":
            return param_value * (1 + (feature_value - 0.5) * strength)
        else:  # absolute
            return param_value * feature_value * strength

    def apply_effect(self, audio, frame_rate, screen_width, screen_height, strength, feature_param, feature_mode, opt_feature=None, **kwargs):
        # Calculate num_frames based on audio duration and frame_rate
        audio_duration = len(audio['waveform'].squeeze(0).mean(axis=0)) / audio['sample_rate']
        num_frames = int(audio_duration * frame_rate)

        # Initialize the audio processor
        processor = BaseAudioProcessor(audio, num_frames, screen_height, screen_width, frame_rate)

        # Initialize results list
        result = []

        self.start_progress(num_frames, desc=f"Applying {self.__class__.__name__}")

        for i in range(num_frames):
            # Always get audio data for visualization
            self.get_audio_data(processor, i, **kwargs)

            # Modulate parameters based on feature only if opt_feature is provided
            if opt_feature is not None:
                feature_value = opt_feature.get_value_at_frame(i)
                for param_name in self.get_modifiable_params():
                    if param_name in kwargs:
                        if param_name == feature_param:
                            kwargs[param_name] = self.modulate_param(param_name, kwargs[param_name],
                                                                     feature_value, strength, feature_mode)

            # Generate the image for the current frame
            image = self.draw(processor, **kwargs)
            result.append(image)

            self.update_progress()

        self.end_progress()

        # Convert the list of numpy arrays to a single numpy array
        result_np = np.stack(result)  # Shape: (N, H, W, C)

        # Convert the numpy array to a PyTorch tensor and ensure it's in BHWC format
        result_tensor = torch.from_numpy(result_np).float()

        return (result_tensor,)

    @abstractmethod
    def get_audio_data(self, processor: BaseAudioProcessor, frame_index, **kwargs):
        """
        Abstract method to get audio data for visualization at a specific frame index.

        Returns:
        - feature_value: float, extracted feature value for modulation.
        """
        pass

    @abstractmethod
    def draw(self, processor: BaseAudioProcessor, **kwargs) -> np.ndarray:
        """
        Abstract method to generate the image for the current frame.

        Returns:
        - image: numpy array of shape (H, W, 3).
        """
        pass

class FlexAudioVisualizerBar(FlexAudioVisualizerBase):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            **super().INPUT_TYPES(),
            "required": {
                **super().INPUT_TYPES()["required"],
                "curvature": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 50.0, "step": 1.0}),
                "separation": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 100.0, "step": 1.0}),
                "max_height": ("FLOAT", {"default": 200.0, "min": 10.0, "max": 2000.0, "step": 10.0}),
                "min_height": ("FLOAT", {"default": 10.0, "min": 0.0, "max": 500.0, "step": 5.0}),
                "num_bars": ("INT", {"default": 64, "min": 1, "max": 1024, "step": 1}),
                "smoothing": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "rotation": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 360.0, "step": 1.0}),
                "position_y": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "reflect": ("BOOLEAN", {"default": False}),
            }
        }

    FUNCTION = "apply_effect"

    @classmethod
    def get_modifiable_params(cls):
        return ["curvature", "separation", "max_height", "min_height", "num_bars", "smoothing", "rotation", "position_y", "reflect", "None"]

    def __init__(self):
        super().__init__()
        self.bars = None

    def get_audio_data(self, processor: BaseAudioProcessor, frame_index, **kwargs):
        audio_frame = processor._get_audio_frame(frame_index)
        num_bars = kwargs.get('num_bars')
        smoothing = kwargs.get('smoothing')

        if len(audio_frame) == 0:
            data = np.zeros(num_bars)
        else:
            # Compute the magnitude spectrum
            spectrum = np.abs(np.fft.rfft(audio_frame, n=num_bars * 2))
            # Apply logarithmic scaling
            spectrum = np.log1p(spectrum)
            # Normalize the spectrum data
            if np.max(spectrum) != 0:
                spectrum = spectrum / np.max(spectrum)
            data = spectrum[:num_bars]

        # Initialize bars if not already done
        if self.bars is None or len(self.bars) != num_bars:
            self.bars = np.zeros(num_bars)

        # Update the bar heights with smoothing
        self.bars = smoothing * self.bars + (1 - smoothing) * data

        # Return the mean value as feature_value for modulation
        feature_value = np.mean(self.bars)
        return feature_value

    def draw(self, processor: BaseAudioProcessor, **kwargs):
        """
        Generate the image for the current frame.

        Returns:
        - image: numpy array of shape (H, W, 3).
        """
        # Extract parameters
        curvature = int(kwargs.get('curvature'))
        separation = kwargs.get('separation')
        max_height = kwargs.get('max_height')
        min_height = kwargs.get('min_height')
        num_bars = kwargs.get('num_bars')
        rotation = kwargs.get('rotation') % 360
        screen_width = processor.width
        screen_height = processor.height
        position_y = kwargs.get('position_y')
        reflect = kwargs.get('reflect')

        # Calculate bar width
        total_separation = separation * (num_bars - 1)
        total_bar_width = screen_width - total_separation
        bar_width = total_bar_width / num_bars

        # Baseline Y position
        baseline_y = int(screen_height * position_y)

        # Create an empty image
        image = np.zeros((screen_height, screen_width, 3), dtype=np.float32)

        # Draw bars
        for i, bar_value in enumerate(self.bars):
            x = int(i * (bar_width + separation))

            bar_h = min_height + (max_height - min_height) * bar_value

            # Draw bar depending on reflect
            if reflect:
                y_start = int(baseline_y - bar_h)
                y_end = int(baseline_y + bar_h)
            else:
                y_start = int(baseline_y - bar_h)
                y_end = int(baseline_y)

            # Ensure y_start and y_end are within bounds
            y_start = max(min(y_start, screen_height - 1), 0)
            y_end = max(min(y_end, screen_height - 1), 0)

            # Swap y_start and y_end if necessary
            if y_start > y_end:
                y_start, y_end = y_end, y_start

            x_end = int(x + bar_width)
            color = (1.0, 1.0, 1.0)  # White color

            # Draw rectangle with optional curvature
            rect_width = max(1, int(bar_width))
            rect_height = max(1, int(y_end - y_start))

            if curvature > 0 and rect_width > 1 and rect_height > 1:
                rect = np.zeros((rect_height, rect_width, 3), dtype=np.float32)
                # Create mask for rounded rectangle
                radius = max(1, min(int(curvature), rect_width // 2, rect_height // 2))
                mask = np.full((rect_height, rect_width), 0, dtype=np.uint8)
                cv2.rectangle(mask, (0, 0), (rect_width - 1, rect_height - 1), 255, -1)
                if radius > 1:
                    mask = cv2.GaussianBlur(mask, (radius*2+1, radius*2+1), 0)
                # Apply mask
                rect[mask > 0] = color
                # Place rect onto image
                image[y_start:y_end, x:x+rect_width] = rect
            else:
                cv2.rectangle(image, (x, y_start), (x_end, y_end), color, thickness=-1)

        # Apply rotation if needed
        if rotation != 0:
            image = self.rotate_image(image, rotation)

        return image

    def rotate_image(self, image, angle):
        """Rotate the image by the given angle."""
        (h, w) = image.shape[:2]
        center = (w / 2, h / 2)

        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated_image = cv2.warpAffine(image, M, (w, h))

        return rotated_image

class FlexAudioVisualizerFreqAmplitude(FlexAudioVisualizerBase):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            **super().INPUT_TYPES(),
            "required": {
                **super().INPUT_TYPES()["required"],
                "max_frequency": ("FLOAT", {"default": 8000.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "min_frequency": ("FLOAT", {"default": 20.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "smoothing": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "fft_size": ("INT", {"default": 2048, "min": 256, "max": 8192, "step": 256}),
                "position_y": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "reflect": ("BOOLEAN", {"default": False}),
                "curve_smoothing": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "rotation": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 360.0, "step": 1.0}),
            }
        }

    FUNCTION = "apply_effect"

    @classmethod
    def get_modifiable_params(cls):
        return ["max_frequency", "min_frequency", "smoothing", "fft_size", "position_y", "reflect", "curve_smoothing", "rotation", "None"]

    def __init__(self):
        super().__init__()
        self.spectrum = None

    def get_audio_data(self, processor: BaseAudioProcessor, frame_index, **kwargs):
        fft_size = kwargs.get('fft_size')
        smoothing = kwargs.get('smoothing')

        audio_frame = processor._get_audio_frame(frame_index)

        # Ensure audio_frame has the required length
        if len(audio_frame) < fft_size:
            audio_frame = np.pad(audio_frame, (0, fft_size - len(audio_frame)), mode='constant')

        # Apply window function
        window = np.hanning(len(audio_frame))
        audio_frame = audio_frame * window

        # Compute FFT
        spectrum = np.abs(np.fft.rfft(audio_frame, n=fft_size))

        # Extract desired frequency range
        sample_rate = processor.sample_rate
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
        min_freq = kwargs.get('min_frequency')
        max_freq = kwargs.get('max_frequency')
        freq_indices = np.where((freqs >= min_freq) & (freqs <= max_freq))[0]
        spectrum = spectrum[freq_indices]

        # Apply logarithmic scaling
        spectrum = np.log1p(spectrum)

        # Normalize
        if np.max(spectrum) != 0:
            spectrum = spectrum / np.max(spectrum)

        # Initialize spectrum if not done
        if self.spectrum is None or len(self.spectrum) != len(spectrum):
            self.spectrum = np.zeros(len(spectrum))

        # Apply smoothing over time
        self.spectrum = smoothing * self.spectrum + (1 - smoothing) * spectrum

        # We don't need to return a feature value anymore
        return None

    def smooth_curve(self, y, window_size):
        """Apply a moving average to smooth the curve."""
        if window_size < 3:
            return y  # No smoothing needed
        box = np.ones(window_size) / window_size
        y_smooth = np.convolve(y, box, mode='same')
        return y_smooth

    def draw(self, processor: BaseAudioProcessor, **kwargs):
        max_frequency = kwargs.get('max_frequency')
        min_frequency = kwargs.get('min_frequency')
        position_y = kwargs.get('position_y')
        reflect = kwargs.get('reflect')
        curve_smoothing = kwargs.get('curve_smoothing')
        rotation = kwargs.get('rotation') % 360
        screen_width = processor.width
        screen_height = processor.height

        # Baseline Y position
        baseline_y = screen_height * position_y
        max_amplitude = min(baseline_y, screen_height - baseline_y)

        # Apply curve smoothing if specified
        if curve_smoothing > 0:
            window_size = int(len(self.spectrum) * curve_smoothing)
            if window_size % 2 == 0:
                window_size += 1  # Make it odd
            if window_size > 2:
                spectrum_smooth = self.smooth_curve(self.spectrum, window_size)
            else:
                spectrum_smooth = self.spectrum
        else:
            spectrum_smooth = self.spectrum

        # Compute amplitude
        amplitude = spectrum_smooth * max_amplitude

        # Frequency axis
        num_points = len(amplitude)
        x_values = np.linspace(0, screen_width, num_points)

        # Create an empty image
        image = np.zeros((screen_height, screen_width, 3), dtype=np.float32)

        if reflect:
            # Reflect the visualization
            y_values_up = baseline_y - amplitude
            y_values_down = baseline_y + amplitude

            points_up = np.array([x_values, y_values_up]).T.astype(np.int32)
            points_down = np.array([x_values, y_values_down]).T.astype(np.int32)

            # Draw the curves
            if len(points_up) > 1:
                cv2.polylines(image, [points_up], False, (1.0, 1.0, 1.0))
            if len(points_down) > 1:
                cv2.polylines(image, [points_down], False, (1.0, 1.0, 1.0))
        else:
            # Single visualization
            y_values = baseline_y - amplitude

            points = np.array([x_values, y_values]).T.astype(np.int32)

            if len(points) > 1:
                cv2.polylines(image, [points], False, (1.0, 1.0, 1.0))

        # Apply rotation if needed
        if rotation != 0:
            image = self.rotate_image(image, rotation)

        return image

    def rotate_image(self, image, angle):
        """Rotate the image by the given angle."""
        (h, w) = image.shape[:2]
        center = (w / 2, h / 2)

        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated_image = cv2.warpAffine(image, M, (w, h))

        return rotated_image

class FlexAudioVisualizerCircular(FlexAudioVisualizerBase):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            **super().INPUT_TYPES(),
            "required": {
                **super().INPUT_TYPES()["required"],
                "max_frequency": ("FLOAT", {"default": 8000.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "min_frequency": ("FLOAT", {"default": 20.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "smoothing": ("FLOAT", {"default": 0.5, "min": 0.0, "max":1.0, "step": 0.01}),
                "fft_size": ("INT", {"default": 2048, "min": 256, "max": 8192, "step": 256}),
                "num_points": ("INT", {"default": 360, "min": 3, "max": 1000, "step": 1}),
                "radius": ("FLOAT", {"default": 200.0, "min": 10.0, "max": 1000.0, "step": 10.0}),
                "line_width": ("INT", {"default": 2, "min": 1, "max": 10, "step": 1}),
                "rotation": ("FLOAT", {"default": 0.0, "min":0.0, "max":360.0, "step":1.0}),
            }
        }

    FUNCTION = "apply_effect"

    @classmethod
    def get_modifiable_params(cls):
        return ["max_frequency", "min_frequency", "smoothing", "fft_size", "radius", "num_points", "line_width", "rotation", "None"]

    def __init__(self):
        super().__init__()
        self.spectrum = None

    def get_audio_data(self, processor: BaseAudioProcessor, frame_index, **kwargs):
        audio_frame = processor._get_audio_frame(frame_index)
        fft_size = kwargs.get('fft_size')
        smoothing = kwargs.get('smoothing')
        num_points = round(kwargs.get('num_points'))  # Round to nearest integer

        if len(audio_frame) < fft_size:
            audio_frame = np.pad(audio_frame, (0, fft_size - len(audio_frame)), mode='constant')

        # Apply window function
        window = np.hanning(len(audio_frame))
        audio_frame = audio_frame * window

        # Compute FFT
        spectrum = np.abs(np.fft.rfft(audio_frame, n=fft_size))

        # Extract desired frequency range
        sample_rate = processor.sample_rate
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
        min_freq = kwargs.get('min_frequency')
        max_freq = kwargs.get('max_frequency')
        freq_indices = np.where((freqs >= min_freq) & (freqs <= max_freq))[0]
        spectrum = spectrum[freq_indices]

        # Apply logarithmic scaling
        spectrum = np.log1p(spectrum)

        # Normalize
        if np.max(spectrum) != 0:
            spectrum = spectrum / np.max(spectrum)

        # Resample the spectrum to match the number of points
        data = np.interp(
            np.linspace(0, len(spectrum), num_points, endpoint=False),
            np.arange(len(spectrum)),
            spectrum,
        )

        # Initialize spectrum if not done
        if self.spectrum is None or len(self.spectrum) != num_points:
            self.spectrum = np.zeros(num_points)

        # Apply smoothing
        self.spectrum = smoothing * self.spectrum + (1 - smoothing) * data

        # Return mean spectrum value as feature_value
        feature_value = np.mean(self.spectrum)
        return feature_value

    def draw(self, processor: BaseAudioProcessor, **kwargs):
        max_frequency = kwargs.get('max_frequency')
        min_frequency = kwargs.get('min_frequency')
        num_points = round(kwargs.get('num_points'))  # Round to nearest integer
        radius = kwargs.get('radius')
        line_width = kwargs.get('line_width')
        rotation = kwargs.get('rotation') % 360
        screen_width = processor.width
        screen_height = processor.height

        # Create an empty image
        image = np.zeros((screen_height, screen_width, 3), dtype=np.float32)

        # Center of the screen
        center_x = screen_width / 2
        center_y = screen_height / 2

        # Angles for each point (with rotation)
        angles = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
        rotation_rad = np.deg2rad(rotation)
        angles += rotation_rad

        # Ensure self.spectrum matches num_points
        if len(self.spectrum) != num_points:
            self.spectrum = np.interp(np.linspace(0, 1, num_points), np.linspace(0, 1, len(self.spectrum)), self.spectrum)

        # Compute end points of lines based on spectrum data
        for angle, amplitude in zip(angles, self.spectrum):
            # Start point (on the circle)
            x_start = center_x + radius * np.cos(angle)
            y_start = center_y + radius * np.sin(angle)

            # End point (extended by amplitude)
            extended_radius = radius + amplitude * radius
            x_end = center_x + extended_radius * np.cos(angle)
            y_end = center_y + extended_radius * np.sin(angle)

            # Draw line
            cv2.line(
                image,
                (int(x_start), int(y_start)),
                (int(x_end), int(y_end)),
                (1.0, 1.0, 1.0),
                thickness=line_width,
            )

        return image

class FlexAudioVisualizerCircleDeform(FlexAudioVisualizerBase):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            **super().INPUT_TYPES(),
            "required": {
                **super().INPUT_TYPES()["required"],
                "max_frequency": ("FLOAT", {"default": 8000.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "min_frequency": ("FLOAT", {"default": 20.0, "min": 20.0, "max": 20000.0, "step": 10.0}),
                "smoothing": ("FLOAT", {"default": 0.5, "min": 0.0, "max":1.0, "step": 0.01}),
                "fft_size": ("INT", {"default": 2048, "min": 256, "max": 8192, "step": 256}),
                "num_points": ("INT", {"default": 360, "min": 3, "max": 1000, "step": 1}),
                "base_radius": ("FLOAT", {"default": 200.0, "min": 10.0, "max": 1000.0, "step": 10.0}),
                "amplitude_scale": ("FLOAT", {"default": 100.0, "min": 1.0, "max": 1000.0, "step": 10.0}),
                "line_width": ("INT", {"default": 2, "min": 1, "max": 10, "step": 1}),
                "rotation": ("FLOAT", {"default": 0.0, "min":0.0, "max":360.0, "step":1.0}),
            }
        }

    FUNCTION = "apply_effect"

    @classmethod
    def get_modifiable_params(cls):
        return ["max_frequency", "min_frequency", "smoothing", "fft_size", "base_radius", "num_points", "amplitude_scale", "line_width", "rotation", "None"]

    def __init__(self):
        super().__init__()
        self.spectrum = None

    def get_audio_data(self, processor: BaseAudioProcessor, frame_index, **kwargs):
        audio_frame = processor._get_audio_frame(frame_index)
        fft_size = kwargs.get('fft_size')
        smoothing = kwargs.get('smoothing')
        num_points = round(kwargs.get('num_points'))  # Round to nearest integer

        if len(audio_frame) < fft_size:
            audio_frame = np.pad(audio_frame, (0, fft_size - len(audio_frame)), mode='constant')

        # Apply window function
        window = np.hanning(len(audio_frame))
        audio_frame = audio_frame * window

        # Compute FFT
        spectrum = np.abs(np.fft.rfft(audio_frame, n=fft_size))

        # Extract desired frequency range
        sample_rate = processor.sample_rate
        freqs = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
        min_freq = kwargs.get('min_frequency')
        max_freq = kwargs.get('max_frequency')
        freq_indices = np.where((freqs >= min_freq) & (freqs <= max_freq))[0]
        spectrum = spectrum[freq_indices]

        # Check if spectrum is empty or contains only zeros
        if len(spectrum) == 0 or np.all(spectrum == 0):
            spectrum = np.zeros(num_points)
        else:
            # Apply logarithmic scaling
            spectrum = np.log1p(spectrum)

            # Normalize
            spectrum = spectrum / np.max(spectrum)

        # Resample the spectrum to match the number of points
        data = np.interp(
            np.linspace(0, len(spectrum), num_points, endpoint=False),
            np.arange(len(spectrum)),
            spectrum,
        )

        # Initialize spectrum if not done
        if self.spectrum is None or len(self.spectrum) != num_points:
            self.spectrum = np.zeros(num_points)

        # Apply smoothing
        self.spectrum = smoothing * self.spectrum + (1 - smoothing) * data

        # Return mean spectrum value as feature_value
        feature_value = np.mean(self.spectrum)
        return feature_value

    def draw(self, processor: BaseAudioProcessor, **kwargs):
        max_frequency = kwargs.get('max_frequency')
        min_frequency = kwargs.get('min_frequency')
        num_points = round(kwargs.get('num_points'))  # Round to nearest integer
        base_radius = kwargs.get('base_radius')
        amplitude_scale = kwargs.get('amplitude_scale')
        line_width = kwargs.get('line_width')
        rotation = kwargs.get('rotation') % 360
        screen_width = processor.width
        screen_height = processor.height

        # Create an empty image
        image = np.zeros((screen_height, screen_width, 3), dtype=np.float32)

        # Center of the screen
        center_x = screen_width / 2
        center_y = screen_height / 2

        # Angles for each point (with rotation)
        angles = np.linspace(0, 2 * np.pi, num_points, endpoint=False)
        rotation_rad = np.deg2rad(rotation)
        angles += rotation_rad

        # Ensure self.spectrum matches num_points
        if len(self.spectrum) != num_points:
            self.spectrum = np.interp(np.linspace(0, 1, num_points), np.linspace(0, 1, len(self.spectrum)), self.spectrum)

        # Compute radius for each point
        radii = base_radius + self.spectrum * amplitude_scale

        # Compute x and y coordinates
        x_values = center_x + radii * np.cos(angles)
        y_values = center_y + radii * np.sin(angles)

        # Create points list
        points = np.array([x_values, y_values]).T.astype(np.int32)

        # Draw the deformed circle
        if len(points) > 2:
            cv2.polylines(image, [points], isClosed=True, color=(1.0, 1.0, 1.0), thickness=line_width)

        return image
