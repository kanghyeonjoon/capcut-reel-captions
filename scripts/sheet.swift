// 사용: [CELL_W=320] [CROP=x,y,w,h] sheet 출력.jpg 열수 파일@초 ...  → 장면(영상의 그 시각, 또는 사진)을 격자로 모은 한 장(각 칸 위에 이름@초)
// CROP은 장면 안에서 잘라 볼 곳(왼쪽 위 기준 0~1 비율). 얼굴·눈처럼 작은 곳을 크게 볼 때 쓴다.
import AVFoundation
import AppKit

let args = CommandLine.arguments
let out = args[1]
let cols = Int(args[2])!
let items = Array(args[3...])
let cw = Int(ProcessInfo.processInfo.environment["CELL_W"] ?? "320")!
let ch = Int(ProcessInfo.processInfo.environment["CELL_H"] ?? String(cw * 9 / 16))!
let lh = 22
let rows = (items.count + cols - 1) / cols
let W = cols * cw, H = rows * (ch + lh)
let ctx = CGContext(data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.setFillColor(CGColor(red: 0.1, green: 0.1, blue: 0.1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
var gens: [String: AVAssetImageGenerator] = [:]
for (i, it) in items.enumerated() {
    let p = it.split(separator: "@"); let path = String(p[0]); let t = Double(p[1])!
    let g = gens[path] ?? { let g = AVAssetImageGenerator(asset: AVURLAsset(url: URL(fileURLWithPath: path)))
        g.appliesPreferredTrackTransform = true; g.maximumSize = CGSize(width: 1920, height: 1920)
        g.requestedTimeToleranceBefore = CMTime(seconds: 0.05, preferredTimescale: 600)
        g.requestedTimeToleranceAfter = CMTime(seconds: 0.05, preferredTimescale: 600); return g }()
    gens[path] = g
    let col = i % cols, row = i / cols
    let x = col * cw, y = H - (row + 1) * (ch + lh)
    let still: CGImage? = path.lowercased().hasSuffix(".jpg") || path.lowercased().hasSuffix(".png")
        ? NSImage(contentsOfFile: path)?.cgImage(forProposedRect: nil, context: nil, hints: nil) : nil
    if var img = still ?? (try? g.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil)) {
        if let c = ProcessInfo.processInfo.environment["CROP"]?.split(separator: ",").compactMap({ Double($0) }), c.count == 4,
           let cut = img.cropping(to: CGRect(x: c[0] * Double(img.width), y: c[1] * Double(img.height),
                                             width: c[2] * Double(img.width), height: c[3] * Double(img.height))) {
            img = cut
        }
        let r = min(Double(cw) / Double(img.width), Double(ch) / Double(img.height))
        let w = Double(img.width) * r, h = Double(img.height) * r
        ctx.draw(img, in: CGRect(x: Double(x) + (Double(cw) - w) / 2, y: Double(y) + (Double(ch) - h) / 2, width: w, height: h))
    }
    let label = String(format: "%.1f", t) as NSString
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
    label.draw(at: NSPoint(x: x + 4, y: y + ch + 3), withAttributes: [.font: NSFont.boldSystemFont(ofSize: 15), .foregroundColor: NSColor.yellow])
    NSGraphicsContext.restoreGraphicsState()
}
let rep = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! rep.representation(using: .jpeg, properties: [.compressionFactor: 0.8])!.write(to: URL(fileURLWithPath: out))
