# Piano transcription model

NoteFall listens to piano recordings with the model from

> Qiuqiang Kong, Bochen Li, Xuchen Song, Yuan Wan and Yuxuan Wang,
> "High-resolution Piano Transcription with Pedals by Regressing Onset and
> Offset Times", IEEE/ACM TASLP, 2021. https://arxiv.org/abs/2010.01815

The checkpoint is the one published by the authors on Zenodo
(https://zenodo.org/record/4034264, `CRNN_note_F1=0.9677_pedal_F1=0.9186.pth`).
NoteFall converts it to ONNX once in CI (`scripts/models/export_piano_model.py`)
and the app downloads that file from this repo's `piano-model` release.

The post-processing in `notefall/piano.py` is a numpy port of
[piano_transcription_inference](https://github.com/qiuqiangkong/piano_transcription_inference),
which is under the MIT licence:

```
MIT License

Copyright (c) 2020 Qiuqiang Kong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
