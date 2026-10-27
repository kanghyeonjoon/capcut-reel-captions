import AVFoundation
import Foundation
// 사용: envelope <영상> <출력.bin>  (20ms마다 RMS dB, float32)
let src = URL(fileURLWithPath: CommandLine.arguments[1])
let out = URL(fileURLWithPath: CommandLine.arguments[2])
let asset = AVURLAsset(url: src)
let track = try await asset.loadTracks(withMediaType: .audio).first!
let reader = try AVAssetReader(asset: asset)
let settings: [String: Any] = [AVFormatIDKey: kAudioFormatLinearPCM, AVSampleRateKey: 16000, AVNumberOfChannelsKey: 1,
                               AVLinearPCMBitDepthKey: 16, AVLinearPCMIsFloatKey: false, AVLinearPCMIsBigEndianKey: false, AVLinearPCMIsNonInterleaved: false]
let output = AVAssetReaderTrackOutput(track: track, outputSettings: settings)
reader.add(output)
reader.startReading()
var acc: Double = 0; var n = 0; var vals: [Float] = []
while let buf = output.copyNextSampleBuffer(), let block = CMSampleBufferGetDataBuffer(buf) {
    var len = 0; var ptr: UnsafeMutablePointer<CChar>?
    CMBlockBufferGetDataPointer(block, atOffset: 0, lengthAtOffsetOut: nil, totalLengthOut: &len, dataPointerOut: &ptr)
    let count = len / 2
    ptr!.withMemoryRebound(to: Int16.self, capacity: count) { p in
        for i in 0..<count {
            let x = Double(p[i]) / 32768.0
            acc += x * x; n += 1
            if n == 320 { vals.append(Float(10 * log10(acc / 320 + 1e-10))); acc = 0; n = 0 }
        }
    }
}
let data = vals.withUnsafeBufferPointer { Data(buffer: $0) }
try data.write(to: out)
print("\(vals.count) frames")
