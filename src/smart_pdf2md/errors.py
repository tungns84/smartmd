class Pdf2MdError(Exception):
    pass


class PdfReadError(Pdf2MdError):
    pass


class OcrBackendError(Pdf2MdError):
    pass


class MergeError(Pdf2MdError):
    pass
