import base64
import re
import unicodedata

from email_validator import EmailNotValidError, validate_email


PHONE_RE = re.compile(r"^\d{10,11}$")
BRAZIL_DDDS = {
    "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "21", "22", "24", "27", "28",
    "31", "32", "33", "34", "35", "37", "38",
    "41", "42", "43", "44", "45", "46", "47", "48", "49",
    "51", "53", "54", "55",
    "61", "62", "63", "64", "65", "66", "67", "68", "69",
    "71", "73", "74", "75", "77", "79",
    "81", "82", "83", "84", "85", "86", "87", "88", "89",
    "91", "92", "93", "94", "95", "96", "97", "98", "99",
}
NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[ '\-][A-Za-zÀ-ÖØ-öø-ÿ]+)*$")
SHORT_TEXT_RE = re.compile(r"^[0-9A-Za-zÀ-ÖØ-öø-ÿºª° .,:&\-/()]+$")
ASSET_TAG_RE = re.compile(r"^[0-9A-Za-zÀ-ÖØ-öø-ÿ ._\-/]+$")
DATA_IMAGE_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,", re.IGNORECASE)
DANGEROUS_TEXT_RE = re.compile(
    r"(<|>|javascript\s*:|data\s*:\s*text/html|on[a-z]+\s*=)",
    re.IGNORECASE,
)
ALLOWED_SYMBOL_CHARS = {"º", "ª", "°"}
MAX_IMAGE_BYTES = 1_200_000
COMMON_WEAK_PASSWORDS = {
    "1234567890",
    "123456789",
    "password123",
    "password1234",
    "senha12345",
    "senha123456",
    "admin12345",
    "admin123456",
    "qwerty12345",
    "qwerty123456",
}


def _collapse_spaces(value: str) -> str:
    return re.sub(r"[ \t]+", " ", value.strip())


def _has_invalid_unicode(value: str, *, allow_newlines: bool = False) -> bool:
    for char in value:
        if allow_newlines and char in "\n\r\t":
            continue
        if char in ALLOWED_SYMBOL_CHARS:
            continue

        category = unicodedata.category(char)
        if category.startswith("C") or category.startswith("S"):
            return True

    return False


def normalize_email_address(value: object, *, check_deliverability: bool) -> str:
    try:
        result = validate_email(
            str(value).strip(),
            check_deliverability=check_deliverability,
        )
    except EmailNotValidError as exc:
        raise ValueError("Informe um email válido e ativo.") from exc

    return result.normalized.lower()


def validate_name(value: object) -> str:
    text = _collapse_spaces(str(value))
    if _has_invalid_unicode(text) or not NAME_RE.fullmatch(text):
        raise ValueError("Informe um nome válido, sem números, símbolos ou emoji.")
    return text


def validate_optional_phone(value: object) -> str | None:
    if value is None:
        return None

    raw_value = str(value).strip()
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None

    if raw_value.startswith("+") or (digits.startswith("55") and len(digits) in (12, 13)):
        raise ValueError("Informe somente DDD brasileiro e número, sem DDI ou +55.")

    if not PHONE_RE.fullmatch(digits):
        raise ValueError("Informe telefone brasileiro com DDD e 10 ou 11 números.")

    ddd = digits[:2]
    if ddd not in BRAZIL_DDDS or len(set(digits)) == 1:
        raise ValueError("Informe um DDD brasileiro e telefone válidos.")

    if len(digits) == 11 and digits[2] != "9":
        raise ValueError("Celular brasileiro com 11 números deve começar com 9 após o DDD.")

    return digits


def validate_short_text(
    value: object,
    *,
    field_name: str,
    required: bool = False,
    max_length: int | None = None,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} é obrigatório.")
        return None

    text = _collapse_spaces(str(value))
    if not text:
        if required:
            raise ValueError(f"{field_name} é obrigatório.")
        return None

    if max_length and len(text) > max_length:
        raise ValueError(f"{field_name} deve ter no máximo {max_length} caracteres.")

    if _has_invalid_unicode(text) or not SHORT_TEXT_RE.fullmatch(text):
        raise ValueError(f"{field_name} contém caracteres inválidos.")

    if DANGEROUS_TEXT_RE.search(text):
        raise ValueError(f"{field_name} contém conteúdo não permitido.")

    return text


def validate_asset_tag(value: object, *, max_length: int = 40) -> str | None:
    text = validate_short_text(value, field_name="Patrimônio", max_length=max_length)
    if text and not ASSET_TAG_RE.fullmatch(text):
        raise ValueError("Patrimônio contém caracteres inválidos.")
    return text


def validate_long_text(
    value: object,
    *,
    field_name: str,
    required: bool = False,
    max_length: int | None = None,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} é obrigatório.")
        return None

    text = str(value).strip()
    if not text:
        if required:
            raise ValueError(f"{field_name} é obrigatório.")
        return None

    if max_length and len(text) > max_length:
        raise ValueError(f"{field_name} deve ter no máximo {max_length} caracteres.")

    if _has_invalid_unicode(text, allow_newlines=True):
        raise ValueError(f"{field_name} não aceita emoji ou caracteres invisíveis.")

    if DANGEROUS_TEXT_RE.search(text):
        raise ValueError(f"{field_name} contém conteúdo não permitido.")

    return text


def validate_password(value: object) -> str:
    password = str(value)
    if len(password) < 10:
        raise ValueError("A senha deve ter pelo menos 10 caracteres.")
    if len(password) > 128:
        raise ValueError("A senha deve ter no máximo 128 caracteres.")
    if any(unicodedata.category(char).startswith("C") for char in password):
        raise ValueError("A senha contém caracteres inválidos.")
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", password) or not re.search(r"\d", password):
        raise ValueError("A senha deve ter letras e números.")
    normalized = password.strip().lower()
    if normalized in COMMON_WEAK_PASSWORDS or len(set(normalized)) <= 3:
        raise ValueError("Escolha uma senha menos previsível.")
    return password


def validate_data_image(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return ""

    match = DATA_IMAGE_RE.match(text)
    if not match:
        raise ValueError(f"{field_name} deve ser uma imagem PNG, JPG ou WEBP.")

    image_type = match.group(1).lower()
    payload = text[match.end() :]
    try:
        decoded = base64.b64decode(payload, validate=True)
    except Exception as exc:
        raise ValueError(f"{field_name} está inválida.") from exc

    if len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError(f"{field_name} ultrapassou o tamanho permitido.")

    is_png = decoded.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpeg = decoded.startswith(b"\xff\xd8\xff")
    is_webp = decoded.startswith(b"RIFF") and decoded[8:12] == b"WEBP"

    if image_type == "png" and not is_png:
        raise ValueError(f"{field_name} não parece ser uma imagem PNG válida.")

    if image_type in {"jpg", "jpeg"} and not is_jpeg:
        raise ValueError(f"{field_name} não parece ser uma imagem JPG válida.")

    if image_type == "webp" and not is_webp:
        raise ValueError(f"{field_name} não parece ser uma imagem WEBP válida.")

    return text


def validate_data_images(
    value: object,
    *,
    field_name: str,
    max_items: int = 3,
    max_total_chars: int = 2_600_000,
) -> list[str]:
    if value in (None, ""):
        return []

    if not isinstance(value, list):
        raise ValueError(f"{field_name} deve ser uma lista de imagens.")

    if len(value) > max_items:
        raise ValueError(f"{field_name} aceita no máximo {max_items} imagens.")

    cleaned_images: list[str] = []
    for index, item in enumerate(value, start=1):
        cleaned = validate_data_image(item, field_name=f"{field_name} {index}")
        if cleaned:
            cleaned_images.append(cleaned)

    if sum(len(image) for image in cleaned_images) > max_total_chars:
        raise ValueError(f"{field_name} ultrapassou o tamanho permitido.")

    return cleaned_images
