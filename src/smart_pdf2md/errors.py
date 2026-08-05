class Pdf2MdError(Exception):
    pass


class PdfReadError(Pdf2MdError):
    pass


class OcrBackendError(Pdf2MdError):
    pass


class OcrFatalError(OcrBackendError):
    """Unrecoverable OCR failure — abort the whole job (bad key, no vision, etc.)."""


class MergeError(Pdf2MdError):
    pass
