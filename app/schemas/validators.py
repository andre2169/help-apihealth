import base64
import re
import unicodedata

from email_validator import EmailNotValidError, validate_email


PHONE_RE = re.compile(r"^\d{10,11}$")
INTERNATIONAL_PHONE_RE = re.compile(r"^\+\d{8,15}$")
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

    if raw_value.startswith("+"):
        if digits.startswith("55") and len(digits) in (12, 13):
            national_number = digits[2:]
        elif INTERNATIONAL_PHONE_RE.fullmatch(f"+{digits}") and len(set(digits)) > 1:
            return f"+{digits}"
        else:
            raise ValueError("Informe um telefone internacional válido.")
    elif digits.startswith("55") and len(digits) in (12, 13):
        national_number = digits[2:]
    elif len(digits) in (10, 11):
        national_number = digits
    elif INTERNATIONAL_PHONE_RE.fullmatch(f"+{digits}") and len(set(digits)) > 1:
        return f"+{digits}"
    else:
        raise ValueError("Informe DDI, DDD e telefone válidos.")

    if not PHONE_RE.fullmatch(national_number):
        raise ValueError("Informe um telefone com DDD e 10 ou 11 números.")

    ddd = int(national_number[:2])
    if ddd < 11 or ddd > 99 or len(set(national_number)) == 1:
        raise ValueError("Informe um telefone válido.")

    if len(national_number) == 11 and national_number[2] != "9":
        raise ValueError("Celular com 11 números deve começar com 9 após o DDD.")

    return f"+55{national_number}"


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
    if len(password) < 8:
        raise ValueError("A senha deve ter pelo menos 8 caracteres.")
    if len(password) > 128:
        raise ValueError("A senha deve ter no máximo 128 caracteres.")
    if any(unicodedata.category(char).startswith("C") for char in password):
        raise ValueError("A senha contém caracteres inválidos.")
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", password) or not re.search(r"\d", password):
        raise ValueError("A senha deve ter letras e números.")
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
