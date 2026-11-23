# Generate missing media

`generate-media` makes the wheel pictures, videos and screenshots a wheel is
missing, on the PC. The GUI's **Generate Media** page runs the same commands.

It needs no internet: no scraper account, artwork service or AI. Titles are
drawn with a font Windows already has, and videos are recorded from the games.
Recording and placeholder clips need ffmpeg and ffprobe, next to SpinDoctor's
EXE, on PATH, or in [`ffmpeg_path`](configuration.md). Drawing needs Pillow,
which the Windows EXEs include (`pip install "spindoctor[preview]"` otherwise).

Boxes, discs, cartridges, themes and backgrounds are not made: an invented one
would be wrong art. Import or fetch those.

## In short

```text
spindoctor generate-media list --all
spindoctor generate-media wheel-pictures --system "Sega Naomi" --apply
spindoctor generate-media record --system "Sega Naomi" --count 5 --apply
spindoctor generate-media put-in
spindoctor generate-media put-in --apply
spindoctor generate-media undo --apply
```

Everything made waits in a staging folder of its own, with a `review.html` to
look at. `put-in` then copies it into HyperSpin's media, only where a place is
still empty or holds a placeholder; a drawn title or placeholder replaces only
an older one. Delete a file from the staging folder to leave it out. `undo`
takes the last batch out again and brings back what it replaced; so does
`media-scan --undo`.

After several runs (a re-run of the games that came out badly, a redraw), put
them all in at once with `put-in --all` (GUI: **Put in all waiting**). Each
place gets the best file of all the waiting batches: real media over a drawn
title or placeholder, a video over a still, then the newest. So it doesn't
matter which batch was made first, and one `undo` takes them all out again.

To skip the look first, `--put-in` on `wheel-pictures`, `record` or
`placeholders` puts the batch in as soon as it is made, the same way (GUI: tick
**Put each new batch in when it's made**). A long recording then ends with the
videos on the wheel. The batch stays in staging, and `undo` takes it out.

So each step is its own choice: without `--apply` a run only plans (what, and
for `record` how long) and changes nothing; `--apply` makes into staging;
`--apply --put-in` also puts it in. Only missing media is made and filled by
default. `--overwrite` on `wheel-pictures`, `record`, `menu-video` or `put-in`
also takes games that already have media and replaces it (GUI: tick **Replace
media the games already have**): `wheel-pictures -g "Sega*" --overwrite` draws
those games' titles again whatever they have. The old files are kept, and
`undo` puts them back. Placeholders never replace media, even with it.

Staging is `<output_dir>\generated-media`, or `~/.spindoctor/generated-media`
without an `output_dir`; `--stage-dir` names another. Batches stay there after
`put-in`: delete them by hand when you no longer want them.

## What counts as missing

`list` judges each wheel the way HyperSpin looks for its media.

| Column | Meaning |
|---|---|
| No pic | No `Images\Wheel\<game>.png` (or `.swf`) |
| Hidden | Not on the wheel because of that: `wheels_only=true` |
| Drawn | Only a title SpinDoctor drew |
| No video | No `.mp4`, `.flv` or still where HyperSpin plays the video |
| Still | A `.png` in the video folder, which HyperSpin shows instead of a video |
| Placeh. | Only a placeholder |

Videos are looked for in `Media\<System>\Video`, or only in the folder that
`[video defaults] path=` names. A clone that plays its parent's video
(`use_parent_vids=true`) isn't missing one. Games HyperSpin doesn't list, and
games on the ignore list, are left out. `--details` names the games.

What `list` counts is what HyperSpin shows now. When some of it is made and
waiting in staging, `list` says how much and how to put it in, `--details`
adds "waiting in staging" to those games, and `--json` / `--csv` carry a
`waiting` field.

`audit` counts media slots and knows no stills, redirects or parent videos, so
its numbers differ.

## Wheel pictures

A picture already on the PC is reused when it is clearly the game's: its
parent's, one in the same folder under nearly the same name that belongs to no
game, or the same game's on another wheel (same database name, year and maker).
`--no-copy` skips that. Otherwise the title is drawn as a transparent PNG, the
usual size of that wheel's other pictures (400x175 where there are too few to
tell), in `--style chrome`, `gold` or `white`, or like a lit display: `lcd`
(a handheld's greenish LCD), and `led`, `vfd` and `neon`, which glow in their
colour instead of casting a shadow. `--font` takes a font file, or the name of
one installed on the PC (`--font bahnschrift`, `--font impact`); without it a
heavy font is picked. A wheel's Main Menu logo is drawn the same way:
`--system "Main Menu" --game "<wheel>" --style vfd`.

With `wheels_only=true`, a game without a picture isn't on its wheel, and
appears as soon as it gets one. Such games are left out unless you pass
`--show-hidden`, so extra disks and sides that are meant to stay hidden do.

Drawn titles count as missing, so `fetch-media` or an import replaces them with
a real logo. `--redraw` draws them again in another style. Two different games
of one wheel that would draw the same title (two makers' "Electronic Football")
get what tells their descriptions apart: "Electronic Football - Conic". A
game's regional copies and revisions keep one title.

## Recording games

`record` launches each game through RocketLauncher, as
[launch tests](workflows.md#launch-tests) do, lets it run `--wait` seconds (20),
waits up to `--settle` more (40) for a picture that moves, records `--seconds`
(35), and closes it with its exit key. Play statistics are put back after every
game.

Before it starts:

- It launches nothing without `--apply`, and asks first (`--yes` skips that).
  The plan says how many games and how long: the wait, half the settle time and
  the recording, plus about 18 seconds per game (launch, close, cleanup and the
  pause before the next) and 90 for the run.
- It refuses while HyperSpin or a game is open, and waits until nobody has
  used the keyboard or mouse for 15 seconds.
- It starts no new game after `--minutes` (30). `--resume` carries on later.

While it runs, leave the PC alone. Any key, control-panel button or mouse click
stops it and closes the game; so do **Stop**, **Stop after this game** and
Ctrl+C. Game pads are not watched.

A black or frozen picture, or another window in front of the game, never
becomes its video. A picture is black when 99.99% of it is dark, so a
handheld's small screen on black, or a pinball's few lit LEDs, is not. A picture
that changes nowhere for 2 seconds is standing still; a small change counts (a
ball, a few LEDs), and a take that stands still most of the time makes a still
instead, unless it's black.

Most arcade and console games show their own demo, and that is what gets
recorded. Games that do nothing until someone plays (handheld electronic games,
many computer games) need keys:

- `--press 3:Enter` presses a key that many seconds after each game's window
  opens: Start, or `--press 2:5 --press 3:1` for a coin and Start.
- `--play "Up Down Left Right A B"` then presses one of those keys at random,
  about once a second, while it waits and records.

Use the keys the games are set to (the control panel's, on a cabinet). The
recorder's own key presses don't stop the run; arrow, Home, End, Page Up/Down,
Insert and Delete reach the game as those keys, not the number pad's. Keys that
quit or pause the game don't belong in `--play`. Games like Simon end at the
first wrong key: give them Start in `--play` too, so a new game starts often.
`--settle 3` keeps such runs short, since the game starts moving once played.

Sound is the PC's own output, through Windows' loopback, brought to about
-20 dB. Without a usable sound device the clip is silent; `--no-sound` asks for
that. The clip is H.264 Main with AAC, at most 640x480, at 30 frames a second.
`--crop auto` drops black bars, read from the brightest picture of the whole
take, so a score line or a row of LEDs on black stays in, and a tall game (a
handheld's portrait screen, at least 60% of the height) or a wide one keeps its
shape; `4:3` keeps the middle; `full` keeps the whole screen, bezel and all.
`--screenshots` takes a still only. MAME writes `cfg\<game>.cfg` when a game closes: `--cleanup remove`
takes such files out again (see [launch tests](workflows.md#launch-tests)).

Stills go into the video folder, where HyperSpin shows them in the video's
place. Artwork slots hold boxes, cartridges or discs depending on the theme, so
nothing is put there.

## A wheel's Main Menu video

While a wheel is picked on the Main Menu, HyperSpin plays
`Media\Main Menu\Video\<wheel>.mp4`. `menu-video` makes one from the wheel's
own game videos: 7.5 seconds of each of 8 of them, spread over the wheel, with
short fades, at 640x480 with their sound. `--game` picks the clips (in the
order given), `--count` and `--seconds` change how many and how long. Only
videos already in the wheel's video folder count, not stills, placeholders or
parents' videos, so put the recordings in first. A wheel that has a Main Menu
video is left alone.

```text
spindoctor generate-media menu-video --system "Handheld Electronic Games" --apply
spindoctor generate-media put-in --apply
```

Its Main Menu logo is a wheel picture like any other:
`wheel-pictures --system "Main Menu" --game "<wheel>"`.

## Placeholders

HyperSpin plays its own `Media\Frontend\Video\No Video.flv` for every game with
no video. One new clip there covers the whole cabinet, with nothing to clean up:

```text
spindoctor generate-media placeholders --no-video-clip --apply
spindoctor generate-media put-in --apply
```

Placeholders per game carry its title: a "No video found" clip
(`--kind clip`) or a "No screenshot found" picture (`--kind picture`), for games
with neither a video nor a still.

```text
spindoctor generate-media placeholders --system "Sega Naomi" --apply
spindoctor generate-media remove --system "Sega Naomi" --apply
```

They, and drawn titles, are named in a `spindoctor-placeholders*.json` beside
them, with size and checksum. A file counts as a placeholder only while it still
matches. `audit`, `inspect`, `stats` and `fetch-media` go on counting those
games as missing, and `fetch-media`, `media-add` and `media-scan` replace a
placeholder without `--overwrite`. `doctor` reports what HyperSpin shows, so a
drawn title counts there. `remove` deletes only files that haven't changed;
`--kind drawn` removes drawn titles.

## Limits

- Recording sees what is on the primary monitor. A game that can't be captured
  comes out black and is not saved.
- Other programs' sound is recorded too: close them first.
- Copying staged files by hand works, with the `.json` beside them, but has no
  undo.
