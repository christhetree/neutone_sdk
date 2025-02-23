import base64
from dataclasses import dataclass
import logging
import math
import io
import pkgutil
import tempfile
from typing import Optional, List

import torch as tr
from torch import nn, Tensor
import torchaudio

logging.basicConfig()
log = logging.getLogger(__name__)


@dataclass
class AudioSample:
    audio: Tensor
    sr: int

    def __post_init__(self):
        assert len(self.audio.shape) == 2
        assert (
            self.audio.size(0) == 1 or self.audio.size(0) == 2
        ), "Audio sample audio should be 1 or 2 channels, channels first"


@dataclass
class AudioSamplePair:
    input: AudioSample
    output: AudioSample

    def to_metadata_format(self):
        return {
            "in": audio_sample_to_mp3_b64(self.input),
            "out": audio_sample_to_mp3_b64(self.output),
        }


def audio_sample_to_mp3_bytes(sample: AudioSample) -> bytes:
    buff = io.BytesIO()
    with tempfile.NamedTemporaryFile(suffix=".mp3") as temp:
        torchaudio.save(temp.name, sample.audio, sample.sr)
        with open(temp.name, "rb") as f:
            buff.write(f.read())
    buff.seek(0)
    return buff.read()


def audio_sample_to_mp3_b64(sample: AudioSample) -> str:
    mp3_bytes = audio_sample_to_mp3_bytes(sample)
    return base64.b64encode(mp3_bytes).decode()


def mp3_b64_to_audio_sample(b64_sample: str) -> AudioSample:
    audio, sr = torchaudio.load(io.BytesIO(base64.b64decode(b64_sample)), format="mp3")
    return AudioSample(audio, sr)


def get_default_audio_samples() -> List[AudioSample]:
    """
    Returns a list of audio samples to be displayed on the website.

    The SDK provides one sample by default, but this method can be used to
    provide different samples.

    By default the outputs of this function will be ran through the model
    and the prerendered samples will be stored inside the saved object.

    See get_prerendered_audio_samples and render_audio_sample for more details.
    """
    log.info(
        "Using default sample... Please consider using your own audio samples by overriding the get_audio_samples method"
    )
    wave, sr = torchaudio.load(
        io.BytesIO(pkgutil.get_data(__package__, "assets/default_samples/sample_1.mp3")),
        format="mp3",
    )
    return [AudioSample(wave, sr)]


def render_audio_sample(
    model: "WaveformToWaveformBase",
    input_sample: AudioSample,
    params: Optional[Tensor] = None,
    output_sr: int = 44100,
) -> AudioSample:
    if len(model.get_native_sample_rates()) > 0:
        preferred_sr = model.get_native_sample_rates()[0]
    else:
        preferred_sr = input_sample.sr

    if len(model.get_native_buffer_sizes()) > 0:
        buffer_size = model.get_native_buffer_sizes()[0]
    else:
        buffer_size = 512

    audio = input_sample.audio
    if input_sample.sr != preferred_sr:
        audio = torchaudio.transforms.Resample(input_sample.sr, preferred_sr)(audio)

    audio_len = audio.size(1)
    padding_amount = math.ceil(audio_len / buffer_size) * buffer_size - audio_len
    padded_audio = nn.functional.pad(audio, [0, padding_amount])
    audio_out = tr.hstack(
        [
            model.forward(chunk, params)
            for chunk in padded_audio.split(buffer_size, dim=1)
        ]
    )[:, :audio_len]
    if preferred_sr != output_sr:
        audio_out = torchaudio.transforms.Resample(preferred_sr, output_sr)(audio_out)
    return AudioSample(audio_out, output_sr)
