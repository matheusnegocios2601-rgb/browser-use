#if os(iOS)
import AVFoundation
import GarfadaCore
import Observation
import SwiftUI
import Vision

/// Câmera ao vivo + classificador de imagens da Apple, 100% no aparelho.
/// Nenhuma foto é salva nem enviada: cada quadro é analisado na memória e descartado.
@MainActor
@Observable
final class CameraModel {
	enum Status: Equatable {
		case idle
		case unauthorized
		case unavailable
		case running
	}

	private(set) var status: Status = .idle
	private(set) var detections: [Detection] = []
	var isFrozen = false

	let session = AVCaptureSession()
	private let database: FoodDatabase
	private let classifier = FrameClassifier()
	private let sessionQueue = DispatchQueue(label: "garfada.camera.session")
	private var isConfigured = false
	/// Média móvel por rótulo: evita que o resultado pisque de um quadro para o outro.
	private var smoothed: [String: Double] = [:]

	init(database: FoodDatabase) {
		self.database = database
	}

	func start() async {
		switch AVCaptureDevice.authorizationStatus(for: .video) {
		case .authorized:
			break
		case .notDetermined:
			guard await AVCaptureDevice.requestAccess(for: .video) else {
				status = .unauthorized
				return
			}
		default:
			status = .unauthorized
			return
		}
		if !isConfigured {
			guard configureSession() else {
				status = .unavailable
				return
			}
			isConfigured = true
		}
		classifier.onResult = { [weak self] results in
			Task { @MainActor in self?.ingest(results) }
		}
		let captureSession = self.session
		sessionQueue.async {
			if !captureSession.isRunning { captureSession.startRunning() }
		}
		status = .running
	}

	func stop() {
		let captureSession = self.session
		sessionQueue.async {
			if captureSession.isRunning { captureSession.stopRunning() }
		}
	}

	private func configureSession() -> Bool {
		session.beginConfiguration()
		defer { session.commitConfiguration() }
		session.sessionPreset = .high
		guard
			let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
			let input = try? AVCaptureDeviceInput(device: device),
			session.canAddInput(input)
		else { return false }
		session.addInput(input)

		let output = AVCaptureVideoDataOutput()
		output.alwaysDiscardsLateVideoFrames = true
		output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
		output.setSampleBufferDelegate(classifier, queue: classifier.queue)
		guard session.canAddOutput(output) else { return false }
		session.addOutput(output)
		return true
	}

	private func ingest(_ results: [(label: String, confidence: Double)]) {
		guard !isFrozen else { return }
		let current = Dictionary(results.map { ($0.label, $0.confidence) }, uniquingKeysWith: max)
		var next: [String: Double] = [:]
		for key in Set(smoothed.keys).union(current.keys) {
			let value = 0.6 * (smoothed[key] ?? 0) + 0.4 * (current[key] ?? 0)
			if value >= 0.03 { next[key] = value }
		}
		smoothed = next
		let pairs = next.map { (label: $0.key, confidence: $0.value) }
		detections = Array(database.detections(from: pairs, minimumConfidence: 0.12).prefix(6))
	}
}

/// Recebe os quadros da câmera numa fila própria e roda o `VNClassifyImageRequest` ~2,5x por segundo.
final class FrameClassifier: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
	let queue = DispatchQueue(label: "garfada.camera.vision", qos: .userInitiated)
	var onResult: (([(label: String, confidence: Double)]) -> Void)?
	private var lastRun = Date.distantPast
	private let request = VNClassifyImageRequest()

	func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
		let now = Date()
		guard now.timeIntervalSince(lastRun) >= 0.4 else { return }
		lastRun = now
		guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
		// Câmera traseira com o iPhone em pé: o sensor entrega a imagem deitada.
		let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .right, options: [:])
		do {
			try handler.perform([request])
			let observations = request.results ?? []
			onResult?(observations.map { (label: $0.identifier, confidence: Double($0.confidence)) })
		} catch {
			// Quadro perdido: o próximo resolve. Não há o que mostrar ao usuário.
		}
	}
}

struct CameraPreview: UIViewRepresentable {
	let session: AVCaptureSession

	func makeUIView(context: Context) -> PreviewView {
		let view = PreviewView()
		view.previewLayer.session = session
		view.previewLayer.videoGravity = .resizeAspectFill
		return view
	}

	func updateUIView(_ uiView: PreviewView, context: Context) {}

	final class PreviewView: UIView {
		override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
		var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
	}
}
#endif
