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
still empty or holds a placeholder. Delete a file from the staging folder to
leave it out. `undo` takes the last batch out again and brings back what it
replaced; so does `media-scan --undo`.

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

`audit` counts media slots and knows no stills, redirects or parent videos, so
its numbers differ.

## Wheel pictures

A picture already on the PC is reused when it is clearly the game's: its
parent's, one in the same folder under nearly the same name that belongs to no
game, or the same game's on another wheel (same database name, year and maker).
`--no-copy` skips that. Otherwise the title is drawn as a transparent PNG, the
usual size of that wheel's other pictures (400x175 where there are too few to
tell), in `--style chrome`, `gold` or `white`.

With `wheels_only=true`, a game without a picture isn't on its wheel, and
appears as soon as it gets one. Such games are left out unless you pass
`--show-hidden`, so extra disks and sides that are meant to stay hidden do.

Drawn titles count as missing, so `fetch-media` or an import replaces them with
a real logo. `--redraw` draws them again in another style.

## Recording games

`record` launches each game through RocketLauncher, as
[launch tests](workflows.md#launch-tests) do, lets it run `--wait` seconds (20),
waits up to 40 more for a picture that moves, records `--seconds` (35), and
closes it with its exit key. Play statistics are put back after every game.

Before it starts:

- It launches nothing without `--apply`, and asks first (`--yes` skips that).
  The plan says how many games and how long: about 75 seconds per game.
- It refuses while HyperSpin or a game is open, and waits until nobody has
  used the keyboard or mouse for 15 seconds.
- It starts no new game after `--minutes` (30). `--resume` carries on later.

While it runs, leave the PC alone. Any key, control-panel button or mouse click
stops it and closes the game; so do **Stop**, **Stop after this game** and
Ctrl+C. Game pads are not watched.

A black or frozen picture, or another window in front of the game, never
becomes its video. A frozen picture that isn't black makes a still instead. The
games' own demo is what gets recorded; `--press 12:Enter` presses a key that
many seconds after the window opens, for one named game.

Sound is the PC's own output, through Windows' loopback, brought to about
-20 dB. Without a usable sound device the clip is silent; `--no-sound` asks for
that. The clip is H.264 Main with AAC, at most 640x480, at 30 frames a second.
`--crop auto` drops black bars; `4:3` keeps the middle; `full` keeps the whole
screen, bezel and all. `--screenshots` takes a still only.

Stills go into the video folder, where HyperSpin shows them in the video's
place. Artwork slots hold boxes, cartridges or discs depending on the theme, so
nothing is put there.

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
