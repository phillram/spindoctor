# Vectrex overlays in MESS

A Vectrex draws white vectors, and each game came with a coloured plastic overlay
for the screen. MESS draws those overlays from a layout file. SpinDoctor doesn't
supply overlays; these notes are about showing them when RocketLauncher's MESS
module starts the games. Checked with MESS 0.160: check again after an upgrade,
on a copy first.

## How a game gets its overlay

- **The module asks for a view named after the game.** It starts a Vectrex game with
  `-view "<game>"` when `<MESS folder>\artwork\Vectrex\<game>.png` exists, and with
  `-view standard` when it doesn't. `<game>` is the ROM's name, as on the wheel.
- **MESS reads the views from `artwork\vectrex\vectrex.lay`.** On Windows the
  folder's name can be in any case.
- **MESS takes the first view whose name starts with the name asked for,** ignoring
  case. So `-view "Polar Rescue (USA)"` gets a `Polar Rescue (USA) (Beta)` view that
  comes before it in the file.
- **With no such view, MESS shows the file's first view:** another game's overlay.
- **`-view standard` still finds MESS's own Standard view** when `vectrex.lay` is
  there, so a game without a PNG shows plain white vectors.
- **`Use_Overlays=false`** under `[GCE Vectrex]` in the module's `MESS.ini` starts
  MESS with `-nouse_overlays`, and no game shows its overlay.

## The layout file

One view per game, named exactly as the game's ROM, with the overlay drawn over the
screen. The Vectrex screen is upright, 3 wide by 4 high, and the overlay covers the
same area:

```xml
<?xml version="1.0"?>
<mamelayout version="2">
	<element name="overlay01">
		<image file="Berzerk (World).png" />
	</element>
	<element name="overlay02">
		<image file="Polar Rescue (USA).png" />
	</element>
	<view name="Berzerk (World)">
		<screen index="0">
			<bounds x="0" y="0" width="3" height="4" />
		</screen>
		<overlay element="overlay01">
			<bounds x="0" y="0" width="3" height="4" />
		</overlay>
	</view>
	<view name="Polar Rescue (USA)">
		<screen index="0">
			<bounds x="0" y="0" width="3" height="4" />
		</screen>
		<overlay element="overlay02">
			<bounds x="0" y="0" width="3" height="4" />
		</overlay>
	</view>
</mamelayout>
```

Each PNG goes beside the layout, named as its game, because that's the file the
module looks for:

```text
D:\Arcade\Emulators\MESS\artwork\Vectrex\
    vectrex.lay
    Berzerk (World).png
    Polar Rescue (USA).png
```

The file must be valid XML: write an `&` in a game's name as `&amp;`. If MESS can't
read the file, it ignores it and no game shows an overlay.

## Converting `.art` overlays

MAME and MESS have read only layout files since version 0.107. An older overlay is
a `.art` file with a `.png` beside it, often loose in `artwork\`. MESS ignores these,
so every game shows white vectors. To convert them:

1. **Make one view per game,** named exactly as the game's ROM. An `.art` file's
   `position = 0.0,0.0,1.0,1.0` is the whole screen, so the overlay gets the screen's
   bounds.
2. **Save each PNG in `artwork\Vectrex\` as `<game>.png`.** A set may have one
   overlay twice, under two dumps' CRCs (`Pole Position (USA) (A00ED3D6)` and
   `(C10F37D8)`): use one copy, under the game's name.
3. **Put each view above every longer name it starts with:** `Polar Rescue (USA)`
   before `Polar Rescue (USA) (Beta)`. Views sorted by name are in that order. Sorting
   the PNG file names isn't enough: `Polar Rescue (USA) (Beta).png` comes before
   `Polar Rescue (USA).png`, because a space sorts before a dot.
4. **Alpha can go.** MESS draws an overlay as a colour multiply: white leaves a
   vector white, a colour tints it. A converter can save each PNG as opaque RGB
   (colours unchanged), so every tint is at full strength.

The old `.art` files can then be moved out of `artwork\`; MESS doesn't read them.

## Check it

`doctor` has a **Vectrex overlays** check. For each visible wheel with "vectrex" in
its name that starts with the MESS module, it warns about:

- `.art` overlays whose game has no view in `vectrex.lay`;
- PNGs with no view of the same name, or no `vectrex.lay` at all;
- a game's view that comes after a longer name starting with the game's;
- a view that draws an image or element that isn't there;
- a `vectrex.lay` MESS can't read.

It also notes views that no PNG reaches, and `Use_Overlays=false`. It only reads.
