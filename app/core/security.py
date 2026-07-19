from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def _bcrypt_secret(password: str) -> str:
    """
    O bcrypt usa no máximo 72 bytes. Cortar por byte evita comportamento
    incorreto quando a senha tem acentos ou outros caracteres multibyte.
    """
    return str(password).encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    return pwd_context.hash(_bcrypt_secret(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(_bcrypt_secret(plain_password), hashed_password)
