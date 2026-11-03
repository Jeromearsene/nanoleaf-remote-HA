# Third-party notices

The `hapble` library (and the copy of it vendored in the Home Assistant
integration, `custom_components/nanoleaf_remote/hapble/`) contains portions
derived from the software below. This notice must be kept in copies and
substantial portions of this repository.

## pyhomekit

Portions of the HAP-BLE PDU framing (`pdu.py`), of the request/response
exchange pattern (`transport.py`), of the TLV8 handling (`tlv8.py`) and of the
protocol constants (`uuids.py`) were derived from
[pyhomekit](https://github.com/henridwyer/pyhomekit) by Henri Dwyer, and
reimplemented on top of `bleak` instead of `bluepy`.

pyhomekit is distributed under the MIT license, reproduced here as required:

```text
Copyright 2017 Henri Dwyer

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Other references (acknowledgements)

These projects were read to cross-check protocol details (constants, HKDF
labels, SRP parameters, behaviour of real accessories). No code from them is
included in this repository:

- aiohomekit
- homekit_python
- apple/HomeKitADK
- shairport-sync
- aanon4/HomeKit
- RubyHome

HomeKit and HomeKit Accessory Protocol are trademarks of Apple Inc. This
project is independent and not affiliated with Apple or Nanoleaf.
