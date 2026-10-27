import AVFoundation
import Foundation

// 사용: timeline_audio <출력.m4a> <파일@원본시작@원본길이@타임라인시작@속도> ...
// 컷 편집된 순서·자리 그대로 소리만 이어 붙인다(컷 사이 빈 곳은 조용히). 받아쓰기를 편집본 기준으로 하려고 쓴다.
let args = CommandLine.arguments
let out = URL(fileURLWithPath: args[1])
let ts: CMTimeScale = 48000
let comp = AVMutableComposition()
let track = comp.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)!
var assets: [String: AVURLAsset] = [:]  // 트랙만 들고 있으면 파일이 풀려 넣기가 실패한다
var tracks: [String: AVAssetTrack?] = [:]
for item in args[2...] {
    let p = item.components(separatedBy: "@")
    let start = CMTime(seconds: Double(p[1])!, preferredTimescale: ts)
    var dur = CMTime(seconds: Double(p[2])!, preferredTimescale: ts)
    let at = CMTime(seconds: Double(p[3])!, preferredTimescale: ts)
    let speed = Double(p[4]) ?? 1.0
    if comp.duration < at {
        track.insertEmptyTimeRange(CMTimeRange(start: comp.duration, duration: at - comp.duration))
    }
    if tracks[p[0]] == nil && p[0] != "-" {
        let asset = AVURLAsset(url: URL(fileURLWithPath: p[0]))
        assets[p[0]] = asset
        tracks[p[0]] = try? await asset.loadTracks(withMediaType: .audio).first
    }
    let outDur = CMTime(seconds: dur.seconds / speed, preferredTimescale: ts)
    if let src = tracks[p[0]] ?? nil {
        let range = try await src.load(.timeRange)
        dur = min(dur, range.end - start)
        try track.insertTimeRange(CMTimeRange(start: start, duration: dur), of: src, at: at)
        if speed != 1.0 {
            track.scaleTimeRange(CMTimeRange(start: at, duration: dur), toDuration: outDur)
        }
    } else {
        track.insertEmptyTimeRange(CMTimeRange(start: at, duration: outDur))  // 사진이나 소리 없는 영상
    }
}
guard let ex = AVAssetExportSession(asset: comp, presetName: AVAssetExportPresetAppleM4A) else { exit(1) }
try? FileManager.default.removeItem(at: out)
try await ex.export(to: out, as: .m4a)
print(String(format: "편집본 소리 %.2f초 → %@", comp.duration.seconds, out.path))
