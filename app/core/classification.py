import unicodedata


DEFAULT_SECTORS = (
    "Recepção", "UTI", "Enfermaria", "Laboratório", "Farmácia",
    "Centro Cirúrgico", "Pronto Atendimento", "Radiologia", "Ambulatório",
    "Almoxarifado", "Administrativo", "TI",
)
DEFAULT_CATEGORIES = (
    "Infraestrutura", "Rede", "Hardware", "Software hospitalar", "Impressão",
    "Acesso", "Telefonia", "Internet", "Segurança", "Periféricos",
    "Sistema de gestão hospitalar", "Leitor ou coletor",
)


def classification_key(value: str | None) -> str:
    value = " ".join(str(value or "").split()).casefold()
    return "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
