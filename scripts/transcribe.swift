import Speech
import AVFoundation
import Foundation

// 사용: transcribe <영상/오디오 파일> <출력 json>
let args = CommandLine.arguments
let input = URL(fileURLWithPath: args[1])
let output = URL(fileURLWithPath: args[2])

func exportAudio(_ src: URL) async throws -> URL {
    let asset = AVURLAsset(url: src)
    let dst = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".m4a")
    guard let ex = AVAssetExportSession(asset: asset, presetName: AVAssetExportPresetAppleM4A) else { throw NSError(domain: "export", code: 1) }
    try await ex.export(to: dst, as: .m4a)
    return dst
}

let locale = Locale(identifier: "ko-KR")
let transcriber = SpeechTranscriber(locale: locale, transcriptionOptions: [], reportingOptions: [], attributeOptions: [.audioTimeRange])
if let req = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
    FileHandle.standardError.write("모델 내려받는 중\n".data(using: .utf8)!)
    try await req.downloadAndInstall()
}
let audioURL = try await exportAudio(input)
let file = try AVAudioFile(forReading: audioURL)
let analyzer = SpeechAnalyzer(modules: [transcriber])
var segments: [[String: Any]] = []
let collector = Task {
    for try await r in transcriber.results {
        var words: [[String: Any]] = []
        for run in r.text.runs {
            if let tr = run.audioTimeRange {
                words.append(["t": String(r.text[run.range].characters), "s": tr.start.seconds, "e": tr.end.seconds])
            }
        }
        segments.append(["text": String(r.text.characters), "words": words])
    }
}
if let last = try await analyzer.analyzeSequence(from: file) {
    try await analyzer.finalizeAndFinish(through: last)
} else {
    await analyzer.cancelAndFinishNow()
}
try await collector.value
try? FileManager.default.removeItem(at: audioURL)
let data = try JSONSerialization.data(withJSONObject: ["file": input.path, "segments": segments], options: [.prettyPrinted])
try data.write(to: output)
print("문장 \(segments.count)개 → \(output.path)")
