// 사용: probe 파일...  → 길이, 화면 크기, 초당 장면 수
import AVFoundation
for p in CommandLine.arguments.dropFirst() {
    let a = AVURLAsset(url: URL(fileURLWithPath: p))
    let sem = DispatchSemaphore(value: 0)
    Task {
        let d = (try? await a.load(.duration))?.seconds ?? -1
        if let v = try? await a.loadTracks(withMediaType: .video).first,
           let (sz, fps, tf) = try? await v.load(.naturalSize, .nominalFrameRate, .preferredTransform) {
            let s = sz.applying(tf)
            print((p as NSString).lastPathComponent, String(format: "%.2f초 %.0fx%.0f %.1ffps", d, abs(s.width), abs(s.height), fps))
        }
        sem.signal()
    }
    sem.wait()
}
