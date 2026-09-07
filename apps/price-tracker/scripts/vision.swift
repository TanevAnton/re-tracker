import Foundation
import Vision
import ImageIO

// The PNG is a temporary product-card crop. No network calls, no retained image.
struct Line: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
}
if CommandLine.arguments.count != 2 { exit(64) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false  // Preserve model numbers and suffixes.
do {
    let supported = try request.supportedRecognitionLanguages()
    request.recognitionLanguages = ["en-US", "bg-BG"].filter { supported.contains($0) }
    let handler = VNImageRequestHandler(url: url)
    try handler.perform([request])
    let rows = (request.results ?? []).compactMap { result -> Line? in
        guard let candidate = result.topCandidates(1).first else { return nil }
        return Line(text: candidate.string, confidence: candidate.confidence,
                    x: result.boundingBox.minX, y: result.boundingBox.minY)
    }.sorted { a,b in abs(a.y-b.y) < 0.015 ? a.x < b.x : a.y > b.y }
    let data = try JSONEncoder().encode(rows)
    print(String(data: data, encoding: .utf8)!)
} catch {
    fputs("Vision OCR unavailable\n", stderr)
    exit(1)
}
