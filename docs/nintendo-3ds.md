# Nintendo 3DS games in Azahar

SpinDoctor doesn't install emulators or supply games. These notes are about running
Nintendo 3DS games in Azahar, Citra's successor, from RocketLauncher. Checked with
Azahar 2127.0 on Windows 10: check again after an upgrade, on a copy first.

Azahar is portable when a `user` folder sits beside `azahar.exe`: it then keeps its
settings, saves and system files there instead of in AppData. The settings are in
`user\config\qt-config.ini`. Close Azahar and back the file up before editing it.

## A setting that doesn't take

Each setting in `qt-config.ini` has two lines:

```ini
screen_gap\default=false
screen_gap=5
```

While its `\default` line says `true`, Azahar uses its own default and ignores the value
under it, so editing the value alone changes nothing. Set both lines.

Azahar writes `\default=true` back whenever it saves a value equal to its default. So a
module that sets something before each start, such as the input profile, writes both
lines every time.

## Screens and full screen

| Section | Setting | What it does |
|---|---|---|
| `[Layout]` | `layout_option=0` | The top screen above the touch screen, like the console. `2` shows one screen large and the other small. |
| `[Layout]` | `screen_gap=5` | Pixels between the two screens. |
| `[Renderer]` | `resolution_factor=3` | Draws at 3× the console's resolution. |
| `[UI]` | `fullscreen=true` | Starts in full screen; the `-f` argument does too. |
| `[UI]` | `confirmClose=false` | No "are you sure" box when RocketLauncher closes it. |

Esc leaves full screen by default. If Esc is on the panel, clear that shortcut:
`Shortcuts\Main%20Window\Exit%20Fullscreen\KeySeq=` (empty).

The touch screen takes the mouse. `Hide_Cursor=true` in the wheel's
`Settings\<System>\RocketLauncher.ini` hides the pointer the player needs there;
`Hide_Cursor=custom` shows a cursor from `RocketLauncher\Media\Cursors\<System>\`
instead, such as a stylus.

## Panel and pads

Input profiles are under `[Controls]`: `profiles\size`, then `profiles\1\name`,
`profiles\1\button_a` and so on, counted from 1. `profile=` picks the one in use and
counts from 0, so `profile=0` is `profiles\1`.

**Keys** are Qt key codes. A letter is its capital's character code, and the arrows are
16777234 (Left), 16777235 (Up), 16777236 (Right) and 16777237 (Down). `code:0` binds
nothing.

```ini
profiles\1\button_a\default=false
profiles\1\button_a="code:69,engine:keyboard"
```

Azahar's default keys include letters a panel often sends: `button_home` (B),
`button_power` (V), `button_debug` (O), `button_gpio14` (P), the C-stick (I, J, K, L)
and the circle pad's half-tilt modifier (D). Clear the ones your panel uses. Inside the
circle pad's value, `$0` stands for `:` and `$1` for `,`:

```ini
profiles\1\circle_pad="down:code$016777237$1engine$0keyboard,engine:analog_from_button,left:code$016777234$1engine$0keyboard,modifier:code$00$1engine$0keyboard,modifier_scale:0.500000,right:code$016777236$1engine$0keyboard,up:code$016777235$1engine$0keyboard"
```

**PS4 pads** work through SDL's game-controller numbering. With `maptype:all`, the pad on
`port:0` answers whatever its GUID, so the profile needs no pad ID:

```ini
profiles\2\button_a="api:controller,button:1,engine:sdl,guid:0,maptype:all,port:0"
profiles\2\button_zl="api:controller,axis:4,direction:+,engine:sdl,guid:0,maptype:all,port:0,threshold:0.500000"
profiles\2\circle_pad="api:controller,axis_x:0,axis_y:1,deadzone:0.100000,engine:sdl,guid:0,maptype:all,port:0"
```

The buttons are Cross 0, Circle 1, Square 2, Triangle 3, Share 4, Options 6, L1 9, R1 10
and the D-pad 11 to 14 (Up, Down, Left, Right). The axes are the left stick 0 and 1, the
right stick 2 and 3, L2 4 and R2 5. For the 3DS's own button positions: A on Circle,
B on Cross, X on Triangle, Y on Square.

**One source per button.** Each 3DS button takes one binding, so a profile is either the
panel or the pad. The module can pick before each start, when it knows whether a pad is
on (`padOn`, found as in [Xbox games](xbox.md#ps4-pads)):

```autohotkey
IniWrite("false", azaharIni, "Controls", "profile\default")
IniWrite(padOn ? "1" : "0", azaharIni, "Controls", "profile")
```

The pad has to be on before the game starts.

## Starting games from RocketLauncher

The wheel's `Settings\<System>\Emulators.ini`:

```ini
[ROMS]
Default_Emulator=Azahar
[Azahar]
Emu_Path=..\Emulators\Azahar\azahar.exe
Rom_Extension=3ds|cci|zip
Module=Azahar.ahk
```

The parts of the module that matter:

```autohotkey
7z(romPath, romName, romExtension, 7zExtractPath,,,keepUnpacked = "true")
gameWindow := "| ahk_exe " . executable
Run(executable . " -f """ . romPath . "\" . romName . romExtension . """", emuPath)
WinWait(gameWindow,, 60, "Secondary Window")
WinActivate(gameWindow,, "Secondary Window")
```

**Wait for the game's own window.** Azahar keeps hidden helper windows, one titled just
`Azahar` and another ending in `| Secondary Window`. RocketLauncher's window commands see
hidden windows, so waiting for `ahk_exe azahar.exe` alone finds a helper straight away.
The game's window is titled `Azahar 2127.0 | <game>`: wait for the `|` and leave out
`Secondary Window`. Close that window the same way in `CloseProcess`. If there is no game
window (an error box instead), close the process.

## Games

- **Decrypted dumps only.** Azahar runs decrypted `.3ds` and `.cci` files. An encrypted
  one stops at a message that the application is encrypted.
- **`.cia` files are installers.** Azahar installs them into its own system storage and
  runs them from its game list; RocketLauncher can't start one by its path.
- **Keep the games unpacked.** 3DS games run to several GB, so unpacking a zip takes a
  while at every start. Point the wheel's `7z_Extract_Path` (under `[7z]` in its
  `RocketLauncher.ini`) at a big drive, and keep what is unpacked there:
  - `7z()`'s seventh argument, `AllowLargerFolders`, reuses a kept folder even if it has
    grown since.
  - Don't call `7zCleanUp()` after the game: it deletes all but the last few
    (`7z_Games_to_Keep`; see [unpacked games](xbox.md#unpacked-games)).

  A kept game starts in seconds. A whole wheel of about 160 games took about 190 GB.

## Miis

Games that let the player pick a Mii, such as Mario Kart 7, Tomodachi Life and Miitopia,
read the console's Mii list. Games that draw Miis themselves, such as Miitopia, also need
the console's Mii face data. A new Azahar install has neither: its Mii list is empty, and
it has only a stand-in for the face data.

### An empty Mii list

The Mii list is Mii Maker's database, `CFL_DB.dat`. In a portable Azahar it is:

```text
user\nand\data\00000000000000000000000000000000\extdata\00048000\F000000B\user\CFL_DB.dat
```

A new install's list holds no Miis, so a game's Mii picker shows none. Shared Mii QR codes
can fill it. The data formats are on 3DBrew's [Mii](https://www.3dbrew.org/wiki/Mii) and
[Mii Maker](https://www.3dbrew.org/wiki/Mii_Maker) pages; the steps, checked with Azahar
2127.0:

1. **Read each QR code as bytes, not text.** A 3DS Mii code holds 0x70 bytes: an 8-byte
   nonce, 0x58 bytes encrypted with AES-CCM, and a 16-byte tag. A QR reader can miss the
   small codes in a gallery picture until the picture is scaled up.
2. **Decrypt it** with the AES key Mii Maker uses for its QR codes (open source Mii QR
   tools carry it): AES-CCM, with the nonce plus 4 zero bytes and the 16-byte tag. Drop
   any code whose tag doesn't match. The Mii is 0x60 bytes: the first 12 decrypted bytes,
   then the 8-byte nonce, then the rest. Its last 2 bytes are a CRC16/XMODEM of the 0x5E
   bytes before them, big-endian: drop any Mii whose CRC is wrong.
3. **Copy its first 0x5C bytes into a free slot.** The list has 100 slots of 0x5C bytes,
   starting at offset 0x8. A slot holds a Mii when its Mii ID (the 4 bytes at slot +
   0xC) isn't 0. That is how Azahar's own Mii picker counts them, so fill only slots
   whose ID is 0.
4. **Set its place in Mii Maker's list:** byte 2 of the slot, with the place on the page
   (0 to 9) in the high 4 bits and the page in the low 4 bits.
5. **Update the file's checksum:** a CRC16/XMODEM of bytes 0x0 to 0xC81D, stored big-endian
   at 0xC81E. Leave every other byte as it was.

Close Azahar and back the file up first. A Mii's name is 10 UTF-16 characters at slot +
0x1A, if you want to give one a name players can read. Shared galleries also hold Miis you
may not want on a cabinet, so look at them before you add them.

### Mii heads show a red no-entry sign

In a game that draws Miis itself, such as Miitopia, every Mii's head is a red "no entry"
sign. Azahar's log, `user\log\azahar_log.txt`, says:

```text
Service.FS <Warning> core\file_sys\archive_ncch.cpp:FileSys::NCCHArchive::OpenFile:179: Mii data file missing. Loading open source replacement from memory
```

The console's Mii face data isn't installed. It is the shared data title
`0004009B00010202`, which holds `CFL_Res.dat`. Without it Azahar uses an open source
stand-in, and Miitopia draws no faces with that.

Get the title from your own 3DS, in one of two ways:

- **Azahar's Artic Setup Tool:** run it on the 3DS, then in Azahar choose
  **File > Set Up System Files...** and the Old 3DS setup. It installs `CFL_Res.dat` with
  the other system files Azahar uses. It also installs data unique to that console, so
  don't share your `user` or `nand` folder afterwards (Azahar's own warning).
- **GodMode9:** dump the console's own copy of title `0004009B00010202` as a decrypted
  CIA, then install it in Azahar with **File > Install CIA...**.

Then start the game again: the faces show, and the "Mii data file missing" line is gone
from the log.

### Old Citra dumps are ignored

A `user` folder from an older Citra setup can hold the face data as a loose RomFS file,
`nand\00000000000000000000000000000000\title\0004009b\00010202\content\00000000.app.romfs`,
with no `00000000.app` beside it. Copied into Azahar 2127, it changes nothing: the heads
stay red and the log still says "Mii data file missing". The log can also say
`Loaded NCCH ...00000000.app is tainted` for that folder; that doesn't mean the file was
used.

Azahar reads a `.romfs` file only as an override of a real `00000000.app` beside it. In
`NCCHArchive::OpenFile`, `GetTitleContent` gives back an empty file when there is no
`00000000.app`, so `NCCHContainer::Load` fails, and `ReadRomFS` returns before it looks
for the override. Azahar then uses its stand-in.

Set the title up again from the console (above), or wrap the same RomFS in a decrypted
NCCH and save it as `00000000.app` in that `content` folder. The `.romfs` file isn't
needed beside it. The layout, copied from a real decrypted 3DS file (numbers
little-endian):

| Offset | Value |
|---|---|
| 0x100 | `NCCH` |
| 0x104 | Content size in 0x200-byte units. It must not equal the size in bytes, or Azahar reads the file as a prototype. |
| 0x108, 0x118 | Partition ID and program ID, both `0004009B00010202` |
| 0x110, 0x112 | Maker code `00`, NCCH version 2 |
| 0x180, 0x1A4 | 0: no extended header and no ExeFS, as in any system data title |
| 0x18C to 0x18F | Platform 1, content type 1 (data), unit size 0, flags 4 (NoCrypto). Azahar refuses an encrypted NCCH, and the NoRomFS flag (2) hides the data. |
| 0x1B0, 0x1B4 | RomFS offset (8, so 0x1000) and size, in 0x200-byte units |
| 0x1B8, 0x1E0 | Size of the RomFS hash region (the IVFC header and master hash, rounded up to 0x200) and its SHA-256 |
| 0x1000 | The RomFS |

The RomFS is laid out as in real files:

- **IVFC header:** `IVFC`, then 0x10000, the master hash size, and three levels (each a
  logical offset and a size of 8 bytes, then 12, the block size as a power of 2, and 4
  zero bytes). Logical offsets: level 1 at 0, levels 2 and 3 each after the one before,
  rounded up to 0x1000. Then 0x5C at 0x54.
- **Master hash** at 0x60.
- **Level 3**, the `.romfs` file as it is, at 0x1000; then level 1, then level 2, each
  starting on a 0x1000 boundary.
- **Hashes:** level 2 holds a SHA-256 of each 0x1000-byte block of level 3, level 1 one
  of each block of level 2, and the master hash one of each block of level 1.

Azahar doesn't follow the IVFC levels: it reads the data from the RomFS offset × 0x200 +
0x1000. So level 3 has to start 0x1000 into the RomFS. Before copying the file in, check
that the bytes from that point on are the `.romfs` file, byte for byte, and that its file
table names `CFL_Res.dat`. Then start a game and check the log as above.
