# Getting a better "Hey Bob"

The "hey bob" model you downloaded works, but in my tests (computer-generated voices, so treat the numbers
as a rough guide) it heard a plain "Hey Bob" almost every time while also waking to look-alikes
("Hey Rob", "Hey Bobby", "Hey Boss", "Hey Mom"), missing some pauses and longer phrases, and doing badly
in background noise. A model trained with more data fixes most of that. This guide covers how to train one
yourself, how to check whether it is better than what you have, and what to do while you decide.

Everything below was checked against openWakeWord's own documentation and example config, except the
parts marked *(my advice)*.

## 1. Why the current model is mediocre

openWakeWord's *detailed training notebook* (`notebooks/automatic_model_training.ipynb`) is deliberately
set up as a quick demo: it makes only 1,000 example clips, trains for 10,000 steps, and lowers its quality
targets (accuracy 0.6, recall 0.25) so it finishes quickly on a free Colab machine. The project's own example
config uses much bigger numbers. A model made with demo-sized settings tends to look like yours. I can't see the quick notebook's defaults, but
its four options (below) are the same levers. The project's README says the quick notebook's output "may be low" in performance in
some deployments, and that performance "seems to increase smoothly with increasing dataset size".

## 2. Train a better one

There are two notebooks, and they offer very different amounts of control:

| | Quick notebook (the one linked from the project README) | Detailed notebook |
|---|---|---|
| Where | A Google Colab page on Google Drive | `notebooks/automatic_model_training.ipynb` in the project |
| What you can set | Four options: `target_word`, `number_of_examples`, `number_of_training_steps`, `false_activation_penalty` | About a dozen, including `custom_negative_phrases` and your own background noise |
| Can I read it? | **No.** It is only on Google Drive and needs a sign-in, so everything about it below comes from your description of its four options, plus general reasoning | Yes, I checked it and the project's example config |

### 2a. With the quick notebook (four options)

*(If it stops with the errors in 2c, skip to 2c first.)*

I can't see this notebook's defaults or its explanatory text, so treat what follows as a method, not a recipe.
Change **one thing at a time**, train, score the result with the tool in section 3, and write the scores down.
That is the only reliable way to find out what helps.

| Option | What to try | Why |
|---|---|---|
| `target_word` | `hey bob` first. If it asks for a phonetic spelling, try variants (and see the note on longer phrases below) | the phrase is the biggest factor in how easy the model is to train |
| `number_of_examples` | **Raise it a lot** (the project says a minimum of several thousand and that performance "seems to increase smoothly with increasing dataset size"; its detailed config asks for at least 20,000). Use the largest your Colab session finishes | the demo-sized default is the most likely reason your model is weak |
| `number_of_training_steps` | Raise it to match (the detailed config uses 50,000 steps; the demo uses 10,000) | more data needs longer training |
| `false_activation_penalty` | Raise it **moderately, in steps**, and score each result. The notebook describes it as how strongly false activations are penalised in training: higher values make the model "much less likely to activate when it shouldn't", but it "may also" fail to activate when the wake word is spoken unclearly and there is background noise | this is your look-alike problem, but see the trade-off below |

**The trade-off matters for you.** Your current model already misses "Hey Bob" in background noise (in my test it
did badly with noise and with some pauses), and a higher `false_activation_penalty` pushes further toward missing
quiet, unclear or noisy speech. Bob can also catch false wakes in software: with `wake_confirm = true` he
double-checks the name in the transcript, which cancelled the "Hey Rob", "Hey Bobby", "Hey Boss" and "Hey Mom" wakes
in my test. A missed "Hey Bob" is more annoying than a false wake that gets cancelled, so the sensible plan is:
**get more examples and steps first (these usually help both problems), keep the penalty moderate, and leave
`wake_confirm` on to mop up the look-alikes**, rather than pushing the penalty high. If you do raise it a lot, test
with the motors running and a TV on, because that is where a too-strict model fails.

Suggested sequence: (1) run with your current settings and score it, to get a baseline that matches your downloaded
model; (2) raise `number_of_examples` and `number_of_training_steps` together, and score again; (3) raise
`false_activation_penalty` in small steps and score each time (including the noisy recordings); (4) keep the best.

Whatever the notebook names its download, rename the `.onnx` file to `hey_bob.onnx` (or after your phrase, for
example `okay_bob.onnx`) before putting it in `wakewords/`: Bob works out the spoken words from the file name, and
uses them to strip "hey bob" from what you say and to double-check the name.

What the quick notebook **can't** do, as far as the four options show: tell the model which specific words to
avoid ("hey rob", "hey boss"), or mix in your own room noise. For those, use the detailed notebook (2b). It is
the same kind of Colab notebook; you edit a few numbers in a settings cell.

### 2b. With the detailed notebook (about an hour of your time, plus waiting)

You need a Google account and the free Google Colab (it provides a GPU). It runs on Linux in the cloud, so it
works from your Mac's browser. No coding is required, but you will edit a few numbers in the settings cell.

1. Open the detailed notebook in Colab (the standard Colab link for a GitHub notebook):
   `https://colab.research.google.com/github/dscripka/openWakeWord/blob/main/notebooks/automatic_model_training.ipynb`
   Then choose **Runtime → Change runtime type → T4 GPU**. The notebook's own notes say its first step takes
   about 10 minutes on a free T4 at demo size; a bigger run takes longer, so expect an hour or more in total.
2. Run the cells from the top. The notebook downloads its training audio itself: room acoustics recordings,
   background sound (AudioSet, music), and a large set of pre-computed "not the wake word" features.
3. In the cell that sets the configuration, change these values from the demo's:

   | Setting | Demo value | Use instead | Why |
   |---|---|---|---|
   | `target_phrase` | `["hey sebastian"]` | `["hey bob"]` | your phrase |
   | `model_name` | derived from the phrase | `hey_bob` | the file name is how Bob finds the spoken words, so keep it `hey_bob` |
   | `n_samples` | 1000 | **20000 or more** | the project's example config asks for at least 20,000 (it suggests 100,000+ can be better) |
   | `n_samples_val` | 1000 | 2000 | the example config's value |
   | `steps` | 10000 | **50000** | the example config's value; more data benefits from longer training |
   | `target_accuracy` / `target_recall` | 0.6 / 0.25 (lowered for the demo) | leave at the notebook's normal defaults (0.7 / 0.5) | the demo lowers them just to finish quickly |
   | `target_false_positives_per_hour` | (example config) 0.2 | keep 0.2, or lower | this is the number you care about most |
   | `max_negative_weight` | (example config) 1500 | raise (for example 3000) if false wakes remain | the example config says raising it may help reach the false-positive target |
   | `custom_negative_phrases` | `[]` | see below | tells it which sounds must NOT wake it |

4. **List your look-alikes in `custom_negative_phrases`**, the single most useful change for your problem. The
   training already adds words that overlap in sound with your phrase automatically; this adds the specific
   ones you saw fire:
   ```
   ["hey rob", "hey bobby", "hey boss", "hey bomb", "hey mom", "hey bud", "hey job", "hey blob", "hey bill", "hey bub"]
   ```
   Add the names of people in your home and anything else you have heard Bob wake to.
5. *(my advice)* **Add your own noise.** The notebook mixes background audio into the training clips, and it
   supports several folders of it (`background_paths`). The most relevant sound for Bob is Bob: record 10 to 30
   minutes of your room with the robot's motors and wheels running, plus TV, a fan, or whatever is normal, using
   the same microphone (`arecord -D <device> -f S16_LE -r 16000 -c 1 -d 600 room.wav`), upload the WAV
   files to Colab, and add that folder to `background_paths`.
6. Run the training cells. When it finishes, the notebook saves `hey_bob.onnx` (and a `.tflite`) in a
   `my_custom_model` folder. Download the **`.onnx`** file. (Free Colab sessions can time out on long runs; if
   you can, keep the page open and active, and download the file as soon as it appears.)

*(my advice)* **A longer phrase is easier to train than a short name.** "Bob" is one short syllable, so lots of
ordinary sounds resemble it. Models generally separate longer phrases from everything else more reliably:
"okay Bob" or "hey Bob-bot" would probably do better than "hey Bob". If you change it, name the file after the
phrase (for example `okay_bob.onnx`); Bob reads the spoken words from the file name.

### 2c. If the notebook fails on Colab (as of October 2026, the official ones do)

If you see `No matching distribution found for piper-phonemize-cross`, then `torchvision==0.20.0` not found, then
`ModuleNotFoundError: No module named 'piper_phonemize'`, the cause is not you or your settings. Colab now runs
Python 3.13, and the official notebooks install older, pinned packages that have no builds for it. Re-running
won't help. The project's own issue about this ([#296](https://github.com/dscripka/openWakeWord/issues/296))
has been open since November 2025 with no official fix, and one user in it says the notebook "has accumulated a
lot of rot". The community has produced patched notebooks. The one I would try is
[alfiedennen/openwakeword-colab-2026](https://github.com/alfiedennen/openwakeword-colab-2026).

**What it is.** A community notebook (MIT licence, not made by the openWakeWord author) that patches those
problems and trains a model the same way. I read all 31 cells of it: it installs packages from PyPI (including a
third-party copy of `piper-phonemize`), clones the openWakeWord and Piper repositories, and downloads data from
GitHub, Hugging Face and a music archive. It does **not** mount your Google Drive, ask for any token or password,
upload anything, or hide code. Two cautions that apply to any notebook like this: it clones openWakeWord's latest
code unpinned and doesn't check any download against a checksum, so it trusts those sources. Use it in a
throwaway session, don't mount your Drive if it ever offers to, and never paste a password or API key into it.

**How to use it.**
1. In Colab choose **File → Open notebook → GitHub tab**, paste `alfiedennen/openwakeword-colab-2026`, open
   `train_wakeword.ipynb`.
2. **Runtime → Change runtime type**: a GPU. The author recommends an L4 with High RAM (Colab Pro, about $10 a
   month, 75–90 minutes). A free T4 also works but takes around 2.5 hours, and the session can drop if you background
   the tab, so keep it open and your computer awake.
3. Find the heading **"10. Build training config (no example-yaml dependency)"**. Colab doesn't number
   its cells, so look for the heading; the code cell right below it is the one with all the settings. Change these two
   lines near the top of that cell, and leave the rest of those lines alone:
   ```python
   TARGET_PHRASE = ['hey bob']
   MODEL_NAME    = 'hey_bob'
   ```
4. Further down in the **same cell** is the training configuration. Its defaults are small: `n_samples` 2000,
   `n_samples_val` 1000, `steps` 20000, `augmentation_rounds` 1, `max_negative_weight` 1500, `target_accuracy` 0.7,
   `target_recall` 0.5, `target_false_positives_per_hour` 0.5. The notebook says its training step takes about 30 to 40
   minutes on a good GPU at the defaults, and bigger values take proportionally longer.
   - **First run:** change only `n_samples` to about 6000 and `steps` to about 30000. Score the result (section 3).
   - **Then, as separate runs:** `max_negative_weight = 3000` (the notebook's own comment: "bump to 3000 if FP rate
     too high"); `target_false_positives_per_hour = 0.2`; `augmentation_rounds = 2`. Compare each against the first run.
5. Choose **Run all**, wait, and the last cell downloads `hey_bob.onnx`. It gives you the `.onnx` file Bob needs.

**Known problem on Colab's Python 3.13, and a fix (found October 2026).** Cell 1 ("1. Comprehensive install") installs
everything and then checks that it all imports. Its line `!pip install -q piper-phonemize-cross` has no Python 3.13
build, so you get `No matching distribution found for piper-phonemize-cross`, and the check at the end of that same cell
stops with `ModuleNotFoundError: No module named 'piper_phonemize'`. (The line `/sbin/ldconfig.real: ... libtbb.so.12
is not a symbolic link` is a harmless Colab warning; ignore it.) The fix is one line, inside cell 1. Change

```
!pip install -q piper-phonemize-cross
```

to

```
!pip install -q piper-phonemize-fix
```

and run cell 1 again. This is a community rebuild of the same library that does have Python 3.13 wheels, with the same
module name. When it works, the cell ends with `All openwakeword deps (incl. piper-tts) import cleanly.` Then carry
on with the other cells as usual (Runtime → Run all, or run them one by one).

About that package: it is an unofficial rebuild by one person (the repository
[easyaspi314/piper-phonemize-fix](https://github.com/easyaspi314/piper-phonemize-fix), which says it is a fork of the
Piper maintainers' `piper-phonemize` with packaging fixes), not an official release. I looked inside its wheel without
running it: it contains the `piper_phonemize` module, the espeak-ng and onnxruntime libraries it needs, and a licence
file. I can't audit the compiled code, so the usual rule applies: run it only in this disposable Colab session, don't
mount your Google Drive, and don't paste any password or key into it.

**A second known problem: the clip-generation step can't find openWakeWord.** Section 11's output shows
`train.py ... ModuleNotFoundError: No module named 'openwakeword'`, then `0 clips`. The notebook's install of
openWakeWord fails on Python 3.13 (it asks for `tflite-runtime`, which has no build for it), and the clip
generator runs as a separate program that can't see it. Two changes, suggested during your run (I haven't
seen them confirmed end to end):
1. Add a code cell just above the section 11 code cell, and run it. It should print `openwakeword OK:` and a path:
   ```
   !pip install -q --no-deps -e /content/openwakeword
   import openwakeword
   print("openwakeword OK:", openwakeword.__file__)
   ```
2. In the section 11 code cell, right after `import sys, os, yaml`, add:
   ```python
   os.environ["PYTHONPATH"] = "/content/openwakeword" + os.pathsep + os.environ.get("PYTHONPATH", "")
   ```
   Then run that cell. It should end with `PASS all 4 clip dirs now populated`.

If a later cell fails with "file not found" (`positive_features_train.npy`) or `best_models is not defined`,
the real error is earlier: scroll up to the first red error in sections 11-13. If Colab restarts the runtime,
re-run the setup cells and the two fixes above before carrying on.

Expect that this may not be the last problem. The notebook was written before Colab's current software (torch 2.11),
and later steps could hit similar version problems. If a cell fails, paste the error and I'll look at it.

It has no list of look-alike words to avoid, so keep `wake_confirm = true` in Bob's config. The author's own
example ("zero phantom fires in 30 minutes") is one test on one device and not an independent measurement:
score the result with the tool in section 3 before trusting it.

**Other routes, if that fails:** Home Assistant's wake word notebook (some people got it working after restarting
the runtime and fixing dependency conflicts); a local trainer for Linux with Python 3.10
([Mobivs/openwakeword-local-trainer](https://github.com/Mobivs/openwakeword-local-trainer), which can't run on a Mac);
or skip training and use the pretrained `hey_jarvis`, which scored perfectly in every test I ran.

## 3. Check whether it is actually better

Don't trust a model (this one, or the new one) until you have heard it on your own voice in your own room.
Bob includes a tool for that:

```
cd ~/bob
.venv/bin/python wakeword_tools.py record --device plughw:1,0
```

It asks you to say "hey bob" six different ways, then look-alike words and normal sentences, then records
room noise, saving them in `wakeword_clips/`. Then score them:

```
.venv/bin/python wakeword_tools.py score wakeword_clips/positive/*.wav wakeword_clips/negative/*.wav
```

You get a score from 0 to 1 per clip; Bob wakes at 0.5 (`wake_threshold`). What you want:
- **At least 9 of 10 "hey bob" recordings above 0.5**, including quiet and fast ones.
- **No look-alike or ordinary-speech recording above 0.5.**
- Try it with the motors running and the TV on, because that is when it will really be used.

Run the same recordings against the old and new model by changing `wake_model` in `config.toml` between runs.
Keep the old file; if the new one is worse, switch back.

**One more thing I learned testing yours:** its scores changed a lot when I shifted the audio by a fraction of
a second (the same "Hey Rob" scored 0.96 in one test and 0.07 in another). That is normal for a weakly trained
model, and it is a good sign if your new model's scores are stable from run to run.

## 4. Install the new model

1. Copy the new file to `wakewords/hey_bob.onnx` in your project (keep the old one as `hey_bob_old.onnx`).
2. Copy it to the Pi with the usual `rsync` command, and restart Bob.
3. Keep `wake_confirm = true` at first (it double-checks the name in the transcript). Once the new model passes
   the checks in section 3, you can try turning it off and see if you miss it.

## 5. While you decide

- **Use the more reliable pretrained word.** `wake_model = "hey_jarvis"` was reliable on every test I ran.
  It's a perfectly good stopgap, and you can call him Bob the rest of the time.
- **Raise the threshold** with `/listen wake threshold 0.8` if he wakes by accident (and lower it if he misses you).
- **Keep `wake_confirm = true`.** It cancelled the "Hey Rob", "Hey Bobby", "Hey Boss" and "Hey Mom" wakes in my test.
- **Use push-to-talk** (`/listen mode ptt`, then Tab) in a noisy room. It never needs a wake word.

## 6. The voice "verifier" (experimental)

openWakeWord can also train a small extra filter on your own voice, which Bob supports
(`.venv/bin/python wakeword_tools.py train`, then set `wake_verifier` in `config.toml`). In my test, using six
"hey bob" and nine other computer-voice clips, it lowered the scores a little but did not separate "Hey Bob"
from "Hey Boss", so I would not count on it. It may do better with real recordings of you, and you can
check that with `score` before trusting it. **A verifier is a Python "pickle" file, and loading one runs
whatever code is inside it, so only ever use one you trained yourself. Never download one.**

## 7. Licence and trust

- openWakeWord's code is Apache 2.0. The project says its *pretrained* models are CC BY-NC-SA 4.0
  (non-commercial), because some of their training data has restrictive licences. A model you train yourself
  with the notebook uses those same datasets, so treat it as for personal, non-commercial use too. That is fine
  for Bob; just don't sell robots with it built in.
- Prefer a model you trained yourself, or one from the project's own community collection, over a file from a
  site that doesn't say who runs it. Whatever you use, only load `.onnx` or `.tflite` files, not pickles.

## Sources

- openWakeWord README, the "Training New Models" section: https://github.com/dscripka/openWakeWord
- The detailed training notebook: `notebooks/automatic_model_training.ipynb` in that repository
- The example training configuration: `examples/custom_model.yml` in that repository
- The open issue about the broken official notebooks: https://github.com/dscripka/openWakeWord/issues/296
- The community notebook discussed in 2c (unofficial): https://github.com/alfiedennen/openwakeword-colab-2026
- Community-trained models (not vetted by me): https://github.com/fwartner/home-assistant-wakewords-collection
