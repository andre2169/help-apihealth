# erros de domínios relacionados

#erros de ticket
class TicketNotFound(Exception):
    """Ticket não encontrado"""
    pass

#erros de status inválido
class TicketInvalidStatus(Exception):
    """Ação não permitida para o status atual do ticket"""
    pass

#erros de permissão
class TicketPermissionDenied(Exception):
    """Usuário não tem permissão para esta ação"""
    pass


#erros de usuário
class UserAlreadyExists(Exception):
    """Email já cadastrado"""
    pass


#erros de autenticação
class InvalidCredentials(Exception):
    """Email ou senha inválidos"""
    pass


class UserNotFound(Exception):
    """Usuário não encontrado"""
    pass


class InvalidUserRole(Exception):
    """Role inválido"""
    pass
