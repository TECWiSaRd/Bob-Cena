import 'dart:typed_data';

/// Splits Bob's video stream (multipart/x-mixed-replace) into JPEG pictures.
///
/// Each part is a boundary line, a Content-Type header, a Content-Length header, a blank line, then that many bytes of JPEG.
class MjpegParser {
  final List<int> _buf = [];
  static const _maxFrame = 8 * 1024 * 1024; // a picture bigger than this means we're reading garbage

  /// Feed bytes as they arrive; returns the complete pictures found so far.
  List<Uint8List> add(List<int> bytes) {
    _buf.addAll(bytes);
    final frames = <Uint8List>[];
    while (true) {
      final headerEnd = _find(const [13, 10, 13, 10], 0);
      if (headerEnd < 0) {
        if (_buf.length > 4096) _buf.clear(); // no header in sight: not a Bob stream
        break;
      }
      final header = String.fromCharCodes(_buf.sublist(0, headerEnd));
      final m = RegExp(r'content-length:\s*(\d+)', caseSensitive: false).firstMatch(header);
      if (m == null) {
        _buf.removeRange(0, headerEnd + 4); // a part without a length: skip it
        continue;
      }
      final length = int.parse(m.group(1)!);
      if (length <= 0 || length > _maxFrame) {
        _buf.clear();
        break;
      }
      final start = headerEnd + 4;
      if (_buf.length < start + length) break; // wait for the rest of the picture
      frames.add(Uint8List.fromList(_buf.sublist(start, start + length)));
      _buf.removeRange(0, start + length);
    }
    return frames;
  }

  int _find(List<int> needle, int from) {
    for (var i = from; i <= _buf.length - needle.length; i++) {
      var ok = true;
      for (var j = 0; j < needle.length; j++) {
        if (_buf[i + j] != needle[j]) {
          ok = false;
          break;
        }
      }
      if (ok) return i;
    }
    return -1;
  }
}
