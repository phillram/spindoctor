NMEmu := "Phoenix"
MEmuV := "v2.8.JAG"
MURL := ["http://www.arts-union.ru/node/23"]
MAuthor := ["djvj"]
MVersion := "2.0.4"
MSystem := ["Atari Jaguar","Panasonic 3DO"]
;----------------------------------------------------------------------------
; Notes:
; Rocketlauncher system name must be "Atari Jaguar" and "Panasonic 3DO"
; 3DO: All game images need to be added to the emulator via "File/Open CD Rom image".
;      A bios file is required.
;      This module allows for per game RAM files by default or a single system wide RAM file.
;      RAM files are required to be made and added to the emulator. To create a RAM file, select "File/New NVRAM storage". Navigate to the emulator/3DO folder, type NVRAM in the file name and click save. A file will be added to the NVRAM list with a red !. Next, again select "File/New NVRAM storage". Navigate to the emulator/3DO folder, select the newly created NVRAM file, a message box will ask if you want to replace it, select yes, and a fixed RAM file will be created. Copy this file for each game and rename them to the same as the game file name.
;      Per game RAM files need to be named the same as the disc image file. System RAM needs to be named NVRAM. RAM files need to be stored in the emulator folder/3DO.
; Jaguar: All game images need to be added to the emulator via "File/Add CARTRIDGE file to the collection".
;----------------------------------------------------------------------------

StartModule()
BezelGUI()
FadeInStart()

Fullscreen := moduleIni.Read("Settings", "Fullscreen","true",,1)
ControlDelay := moduleIni.Read("Settings", "ControlDelay","20",,1) ; raise this if the module is getting stuck somewhere
KeyDelay := moduleIni.Read("Settings", "KeyDelay","-1",,1) ; raise this if the module is getting stuck
GameRAM := moduleIni.Read(romName . "|Settings", "GameRAM","True",,1)

dialogOpen := ("dialog.open") ; Looking up local translation

If bezelEnabled
BezelStart(If Fullscreen = "true" ? "" : "fixResMode")

;hideEmuObj := Object(dialogOpen . " ahk_class #32770",0,"Phoenix ahk_class Qt5QWindowIcon",1) ; Hide_Emu will hide these windows. 0 = will never unhide, 1 = will unhide later
7z(romPath, romName, romExtension, 7zExtractPath)

SetControlDelay, %ControlDelay%
SetKeyDelay(KeyDelay)

If romExtension in .7z,.rar,.zip
ScriptError("Pheonix does not support archived or cue files. Only ""iso"", ""img"", and ""bin"" files can be loaded. Either enable 7z support, or extract your games first.")

HideEmuStart() ; This fully ensures windows are completely hidden even faster than winwait

; Your XML file to be altered in a variable
FileRead, xml, %emuPath%\phoenix.config.xml
StringReplace, xml, xml, `r, , All
romPath2 = %romPath%/%romName%%romExtension%
romPath3 = %romPath%
If GameRAM = False
	ramPath2 = %emuPath%/3DO/NVRAM
If GameRAM = True
	ramPath2 = %emuPath%/3DO/%romName%
ramPath3 = %emuPath%/3DO
StringReplace, romPath2, romPath2, \, /, UseErrorLevel
StringReplace, romPath3, romPath3, \, /, UseErrorLevel
StringReplace, ramPath2, ramPath2, \, /, UseErrorLevel
StringReplace, ramPath3, ramPath3, \, /, UseErrorLevel

If (systemName = "Atari Jaguar")
{
	If (!StringUtils.Contains(xml,"</CARTRIDGE>","CD-ROM")) {
	ScriptError("You don't have any Jaguar games stored in phoenix.config.xml")
	}

	; Use regex to setup the system and game to load
	ToReplace =
	(
	<root [^>]*
	)
	Replacement =
	(
	<root Platform="Jaguar"
	)
	xml := StringUtils.RegExReplace(xml,ToReplace,Replacement )

	; Dump entries in phoenix.config.xml were built from D: drive.
	; ROMs are now at J: — rewrite all Jaguar game Dump paths so Phoenix can find them.
	StringReplace, xml, xml, D:/Arcade/Games/Atari Jaguar/, J:/Games/Atari Jaguar/, All

	; Set attach to the J: path so Phoenix auto-selects this game on startup.
	ToReplace := "<CARTRIDGE expanded=""true"" attach=""[^""]*"""
	Replacement := "<CARTRIDGE expanded=""true"" attach=""" . romPath2 . """"
	xml := StringUtils.RegExReplace(xml, ToReplace, Replacement)

}else{

	If (!StringUtils.Contains(xml,"</CD-ROM>","CD-ROM")) {
	ScriptError("You don't have any 3DO games stored in phoenix.config.xml")
	}

	; Use regex to setup the system and game to load
	ToReplace =
	(
	<root [^>]*
	)
	Replacement =
	(
	<root Platform="3DO"
	)
	xml := StringUtils.RegExReplace(xml,ToReplace,Replacement )

	ToReplace =
	(
	<CD-ROM [^>]*
	)
	Replacement =
	(
	<CD-ROM expanded="true" attach="%romPath2%" last-path="%romPath3%"
	)
	xml := StringUtils.RegExReplace(xml,ToReplace,Replacement )

	If (!StringUtils.Contains(xml,"</NVRAM>","NVRAM")) {
	ScriptError("You don't have any RAM files stored in phoenix.config.xml")
	}

	ToReplace =
	(
	<NVRAM [^>]*
	)
	Replacement =
	(
	<NVRAM expanded="true" attach="%ramPath2%.ram" last-path="%ramPath3%"
	)
	xml := StringUtils.RegExReplace(xml,ToReplace,Replacement )
}

FileDelete, %emuPath%\phoenix.config.xml
FileAppend, %xml%, %emuPath%\phoenix.config.xml

Run(executable, emuPath)
DetectHiddenWindows, on

WinWait("ahk_class Qt5QWindowIcon")
WinWaitActive("ahk_class Qt5QWindowIcon")
Sleep, 1500
;WinMenuSelectItem, ahk_class Qt5QWindowPopupDropShadow,, 2&, 1&

Send, {Alt}{Right}{Enter}{Enter} ; power on roms

If Fullscreen = true
Send, {F11} ; fullscreen

Sleep, 1000

BezelDraw()
HideEmuEnd()
FadeInExit()
Process("WaitClose", executable)
7zCleanUp()
BezelExit()
FadeOutExit()
ExitModule()

HaltEmu:
Send, {pause}
Sleep, 1000
Send, {F11}
Sleep, 2500
FadeOutStart()
Return

RestoreEmu:
Send, {F11}
Sleep, 2000
Send, {pause}
FadeOutExit()
Return

CloseProcess:
FadeOutStart()
WinClose("ahk_class Qt5QWindowIcon") ; Removing Phoenix from the title because the emulator shows statistics in the title while a game is playing
Return
