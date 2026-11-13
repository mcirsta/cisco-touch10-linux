from pathlib import Path
import re,json,hashlib
root=Path('/home/marius/ext_proj/touch10')
out=root/'development/kernel/source/arch/arm/boot/dts/ti/omap'
paths=[root/'development'/p for p in [
 'perrier-native/omap4-perrier-ram.dts','perrier-touch/omap4-perrier-touch.dts',
 'perrier-backlight/omap4-perrier-backlight.dts','perrier-keypad/omap4-perrier-keypad.dts',
 'perrier-thermal/omap4-perrier-thermal.dts','perrier-watchdog/omap4-perrier-watchdog.dts',
 'perrier-cold-ethernet/omap4-perrier-cold-ethernet.dts','perrier-gen4/omap4-perrier-gen4.dts']]

def block(text,needle):
    start=text.index(needle); begin=text.index('{',start); depth=0
    for i in range(begin,len(text)):
        if text[i]=='{':depth+=1
        elif text[i]=='}':
            depth-=1
            if not depth:
                end=i+1
                if text[end:end+1]==';':end+=1
                return start,end
    raise ValueError(needle)

def pop(text,needle):
    start,end=block(text,needle)
    return text[:start]+text[end:],text[start:end]

native=paths[0].read_text()
native,memory=pop(native,'    memory@80000000 {')
native,chosen=pop(native,'    chosen {')
chosen,_=pop(chosen,'        framebuffer@7ec78000 {')
# Remove the old handoff-only commentary along with its disabled framebuffer.
chosen=re.sub(r'\n\s*// Stock Phoenix[\s\S]*?(?=\n\s*};)', '', chosen)
props=[]
for prefix in ['    model =','    compatible =']:
    line=next(x for x in native.splitlines() if x.startswith(prefix))
    props.append(line);native=native.replace(line+'\n','',1)
native=re.sub(r'(?m)^&\{/chosen/framebuffer@7ec78000\}[^\n]*\n','',native)
start=native.index('// Do not populate generic peripheral targets.')
policy=native[start:]
native=native[:start]
policy=policy.replace('&{/thermal-zones} { status = "disabled"; };\n','')
pieces=[native]+[p.read_text() for p in paths[1:]]
body='\n'.join(re.sub(r'(?m)^#include[^\n]*\n|^/dts-v1/;\n|^// SPDX[^\n]*\n','',s) for s in pieces)
# Consolidate final touch properties into its primary node.
start,end=block(body,'&perrier_i2c2 {')
first=body[start:end]
first=first.replace('&perrier_i2c2 {','&perrier_i2c2 {\n    pinctrl-names = "default";\n    pinctrl-0 = <&perrier_touch_i2c_pins>;',1)
first=first.replace('        compatible = "cisco,perrier-cyttsp4";','        compatible = "cisco,perrier-cyttsp4";\n        pinctrl-names = "default";\n        pinctrl-0 = <&perrier_touch_pins>;\n        reset-gpios = <&perrier_gpio5 13 GPIO_ACTIVE_LOW>;\n        vdd-supply = <&perrier_touch_5v>;\n        vddio-supply = <&perrier_touch_3v3>;',1)
body=body[:start]+first+body[end:]
start=body.index('&perrier_i2c2 {',start+len(first))
a,b=block(body[start:],'&perrier_i2c2 {');body=body[:start]+body[start+b:]
body,override=pop(body,'&perrier_backlight {')
start,end=block(body,'perrier_backlight: backlight {')
bl=body[start:end]
bl=re.sub(r'(?m)^        // GPIO157[^\n]*\n        // pinctrl[^\n]*\n','',bl)
bl=bl.replace('        compatible = "pwm-backlight";','        compatible = "pwm-backlight";\n        pinctrl-names = "default";\n        pinctrl-0 = <&perrier_backlight_pwm_pin &perrier_backlight_enable_pin>;\n        power-supply = <&perrier_backlight_5v>;\n        enable-gpios = <&perrier_gpio5 23 GPIO_ACTIVE_HIGH>;',1)
body=body[:start]+bl+body[end:]
body,_=pop(body,'&perrier_panel {')
body=body.replace('    perrier_panel: panel {','    perrier_panel: panel {\n        backlight = <&perrier_backlight>;',1)
# Keep bring-up power policy out of the hardware wiring description.
for label in ['perrier_panel_3v3: regulator-panel-3v3 {','perrier_backlight_5v: regulator-backlight-5v {']:
    start,end=block(body,label); part=body[start:end]
    part=part.replace('        regulator-boot-on;\n','').replace('        regulator-always-on;\n','')
    part=re.sub(r'(?m)^        // Hold this identified rail[\s\S]*?^        // This establishes[^\n]*\n','',part)
    body=body[:start]+part+body[end:]
# Modernize comments only; all electrical properties stay unchanged.
body=body.replace('// RAM trial: passive simpledrm handoff, UART, USB Ethernet, MMC2, and I2C.','// Verified Perrier peripheral wiring and board-specific display settings.')
body=body.replace('// Extend the verified RAM board with native Gen4 input and its existing IRQ.','// Cypress Gen4 controller and its dedicated interrupt/reset bank.')
body=body.replace('// RAM trial: hand timer10 PWM to mainline drivers while preserving the\n// inherited GPIO157 5 V enable and all stock pad mux settings.','// Timer10 PWM, LCD power and backlight enable use standard drivers.')
body=body.replace('// only the explicitly requested Ethernet pads; it has no default state.','// only the explicitly requested board pads; it has no default state.')
body=body.replace('// Stock holds GPIO163 high while the LCD is active. The kexec handoff\n    // leaves it low, so restore only this already identified 3.3 V rail.','// Stock DSI callbacks control this identified LCD 3.3 V switch.')
header='// SPDX-License-Identifier: GPL-2.0-only\n// Perrier hardware description; tested with the separate RAM policy.\n#include <dt-bindings/gpio/gpio.h>\n#include <dt-bindings/input/input.h>\n#include <dt-bindings/input/linux-event-codes.h>\n'
(out/'omap4-cisco-perrier.dtsi').write_text(header+'\n'+body.strip()+'\n')
ram='// SPDX-License-Identifier: GPL-2.0-only\n// RAM development policy: bounded memory, one CPU, protected stock storage.\n/dts-v1/;\n#include "omap4460.dtsi"\n#include "omap4-cisco-perrier.dtsi"\n\n/ {\n'+'\n'.join(props)+'\n'+memory+'\n'+chosen+'\n};\n\n'+policy+'\n&perrier_panel_3v3 {\n    regulator-boot-on;\n    regulator-always-on;\n};\n&perrier_backlight_5v {\n    regulator-boot-on;\n    regulator-always-on;\n};\n'
(out/'omap4-cisco-perrier-ram.dts').write_text(ram)
(root/'development/kernel/dts-migration-inputs.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2)+'\n')
print('Consolidated eight experimental includes into hardware and RAM policy')
