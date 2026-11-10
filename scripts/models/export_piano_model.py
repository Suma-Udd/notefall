"""Turn the ByteDance piano transcription checkpoint into one ONNX file.

    python scripts/models/export_piano_model.py CHECKPOINT.pth OUT_DIR [TEST_AUDIO]

The model is "High-resolution Piano Transcription with Pedals by Regressing
Onset and Offset Times" (Kong et al., 2021), code MIT licensed in
piano_transcription_inference. This runs once in CI (the piano-model
workflow), so NoteFall itself never needs PyTorch. The ONNX file takes 10 s
of 16 kHz mono audio (shape 1 x 160000) and returns the seven output rolls.

With TEST_AUDIO it also checks the ONNX outputs against PyTorch and writes
the reference notes PyTorch finds, so the numpy post-processing in
notefall/piano.py can be checked against the original.
"""

import json
import os
import sys

import numpy as np
import torch

from piano_transcription_inference import PianoTranscription
from piano_transcription_inference.models import Note_pedal

OUTPUTS = ["reg_onset_output", "reg_offset_output", "frame_output", "velocity_output",
           "reg_pedal_onset_output", "reg_pedal_offset_output", "pedal_frame_output"]
SEGMENT = 16000 * 10


class Wrap(torch.nn.Module):
    def __init__(self, model):
        super().__init__()
        self.model = model

    def forward(self, audio):
        d = self.model(audio)
        return tuple(d[k] for k in OUTPUTS)


def main():
    ckpt, out_dir = sys.argv[1], sys.argv[2]
    test = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(out_dir, exist_ok=True)

    model = Note_pedal(frames_per_second=100, classes_num=88)
    model.load_state_dict(torch.load(ckpt, map_location="cpu", weights_only=False)["model"])
    model.eval()

    path = os.path.join(out_dir, "piano-transcription.onnx")
    # batch of one: the GRUs bake their starting state's shape in at export time
    dummy = torch.randn(1, SEGMENT) * 0.05
    torch.onnx.export(Wrap(model), dummy, path, input_names=["audio"], output_names=OUTPUTS,
                      opset_version=17, do_constant_folding=True, dynamo=False)
    print("exported", path, os.path.getsize(path) // 1_000_000, "MB")

    import onnxruntime as ort

    info = {"outputs": OUTPUTS, "segment_samples": SEGMENT, "sample_rate": 16000}
    if test:
        import librosa

        audio, _ = librosa.load(test, sr=16000, mono=True)
        seg = np.zeros((3, SEGMENT), np.float32)
        for i in range(3):
            chunk = audio[i * SEGMENT // 2: i * SEGMENT // 2 + SEGMENT]
            seg[i, :len(chunk)] = chunk
        sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        diffs = {k: 0.0 for k in OUTPUTS}
        for i in range(3):
            with torch.no_grad():
                ref = Wrap(model)(torch.from_numpy(seg[i:i + 1]))
            got = sess.run(None, {"audio": seg[i:i + 1]})
            for k, r, g in zip(OUTPUTS, ref, got):
                diffs[k] = max(diffs[k], float(np.abs(r.numpy() - g).max()))
        print("max abs diff onnx vs torch:", diffs)
        info["max_abs_diff"] = diffs
        assert max(diffs.values()) < 1e-3, diffs

        # reference notes from the original pipeline
        pt = PianoTranscription("Note_pedal", checkpoint_path=ckpt, device=torch.device("cpu"))
        res = pt.transcribe(audio, os.path.join(out_dir, "reference.mid"))
        notes = [[float(e["onset_time"]), float(e["offset_time"]), int(e["midi_note"]),
                  int(e["velocity"])] for e in res["est_note_events"]]
        with open(os.path.join(out_dir, "reference-notes.json"), "w") as fh:
            json.dump({"notes": notes, "pedals": [[float(e["onset_time"]), float(e["offset_time"])]
                                                  for e in res["est_pedal_events"]]}, fh)
        np.savez_compressed(os.path.join(out_dir, "reference-rolls.npz"),
                            **{k: v for k, v in res["output_dict"].items()})
        print("reference notes:", len(notes))
    with open(os.path.join(out_dir, "piano-transcription.json"), "w") as fh:
        json.dump(info, fh, indent=1)


if __name__ == "__main__":
    main()
