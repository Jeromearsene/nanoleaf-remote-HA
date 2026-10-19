"""
SRP-6a côté client, tel que modifié par HAP :
- hash SHA-512 (au lieu de SHA-1 dans le SRP "standard")
- groupe 3072 bits, RFC 5054 Appendix A.4 (N ci-dessous, g=5)
- username fixe : "Pair-Setup"

Constante N vérifiée en la récupérant directement depuis le texte officiel
de la RFC 5054 (https://www.ietf.org/rfc/rfc5054.txt, section Appendix A,
"4. 3072-bit Group") plutôt que reconstituée de mémoire.

Formule de la preuve client (M1) initialement basée sur la signature de la
fonction HAP_srp_proof_m1(M1, userName, salt, A, B, K) dans l'implémentation
open source officielle d'Apple (apple/HomeKitADK, HAPPairingPairSetup.c) —
mais la signature seule ne précisait pas l'encodage exact des paramètres.
Corrigé ensuite grâce à une implémentation Rust documentant explicitement
"la variante SRP exacte utilisée par HomeKit" (vérifiée contre
shairport-sync/aiohomekit) :

    k = H( PAD(N) | PAD(g) )                  (PAD jusqu'à N_BYTES)
    u = H( PAD(A) | PAD(B) )                  (PAD jusqu'à N_BYTES)
    M1 = H( H(N) XOR H(g) | H(I) | s | A | B | K )   (N, g, A, B : minimal)
    M2 = H( A | M1 | K )                      (A : minimal aussi)

Le piège : k et u utilisent bien un remplissage à N_BYTES (384 octets pour
ce groupe), mais M1/M2 utilisent l'encodage big-endian MINIMAL de N, g, A
et B — pas de remplissage. Pour g=5 ça change tout (1 octet vs 384), ce qui
explique un échec de vérification malgré un code d'appairage correct.
"""

import hashlib
import secrets

# --- Groupe 3072 bits, RFC 5054 Appendix A.4 (vérifié depuis le texte RFC) --

_N_HEX = (
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E08"
    "8A67CC74020BBEA63B139B22514A08798E3404DDEF9519B3CD3A431B"
    "302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9"
    "A637ED6B0BFF5CB6F406B7EDEE386BFB5A899FA5AE9F24117C4B1FE6"
    "49286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8"
    "FD24CF5F83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3BE39E772C"
    "180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF695581718"
    "3995497CEA956AE515D2261898FA051015728E5A8AAAC42DAD33170D"
    "04507A33A85521ABDF1CBA64ECFB850458DBEF0A8AEA71575D060C7D"
    "B3970F85A6E1E4C7ABF5AE8CDB0933D71E8C94E04A25619DCEE3D226"
    "1AD2EE6BF12FFA06D98A0864D87602733EC86A64521F2B18177B200C"
    "BBE117577A615D6C770988C0BAD946E208E24FA074E5AB3143DB5BFC"
    "E0FD108E4B82D120A93AD2CAFFFFFFFFFFFFFFFF"
)
N = int(_N_HEX, 16)
G = 5
N_BYTES = (N.bit_length() + 7) // 8  # 384 pour ce groupe (3072 bits)

assert N.bit_length() == 3072, "La constante N n'a pas la bonne taille."
assert N_BYTES == 384

USERNAME = b"Pair-Setup"


def _sha512(*parts: bytes) -> bytes:
    h = hashlib.sha512()
    for part in parts:
        h.update(part)
    return h.digest()


def pad(value: int, length: int = N_BYTES) -> bytes:
    """Convertit un entier en octets big-endian, complétés à gauche par des
    zéros jusqu'à `length` octets (convention PAD() de la RFC 5054)."""
    return value.to_bytes(length, "big")


def _minimal_bytes(value: int) -> bytes:
    """Encodage big-endian MINIMAL (sans remplissage), au moins 1 octet.

    Détail non-standard HAP important : k = H(PAD(N)|PAD(g)) et
    u = H(PAD(A)|PAD(B)) utilisent bien le remplissage à N_BYTES, MAIS la
    preuve M1 elle-même — H(N), H(g), et les A/B insérés directement dans
    M1/M2 — utilise l'encodage big-endian MINIMAL, pas complété. Pour g=5,
    ça fait toute la différence : 1 octet (0x05) au lieu de 384 (383 zéros
    + 0x05). Confirmé par une implémentation Rust de la variante SRP
    HomeKit exacte, elle-même vérifiée contre shairport-sync/aiohomekit.
    """
    if value == 0:
        return b"\x00"
    length = (value.bit_length() + 7) // 8
    return value.to_bytes(length, "big")


class SrpAuthenticationError(Exception):
    """Levée si la preuve du serveur (accessoire) ne correspond pas —
    typiquement un mauvais code à 8 chiffres."""


class SrpClient:
    """État d'une session SRP-6a côté controller (nous)."""

    def __init__(self, username: bytes = USERNAME):
        self.username = username
        self.a: int = 0
        self.A: int = 0
        self.s: bytes = b""
        self.B: int = 0
        self.x: int = 0
        self.u: int = 0
        self.S: int = 0
        self.K: bytes = b""  # clé de session (64 octets, SHA-512(PAD(S)))

    def generate_a(self) -> bytes:
        """Génère la paire éphémère (a, A) et retourne A complété (384o),
        prêt à être placé dans le TLV PublicKey de M3."""
        # 32 octets (256 bits) : conforme à SRP_SECRET_KEY_BYTES chez Apple.
        self.a = int.from_bytes(secrets.token_bytes(32), "big")
        self.A = pow(G, self.a, N)
        return pad(self.A)

    def process_challenge(self, salt: bytes, B_bytes: bytes, password: bytes) -> None:
        """Traite (s, B) reçus dans M2 et calcule x, u, S, K.

        Lève ValueError si B est invalide (B % N == 0 ou u == 0) — ce sont
        des vérifications de sécurité obligatoires (RFC 5054 §2.5.3/2.5.4),
        pas des cas qui devraient arriver en usage normal.
        """
        self.s = salt
        self.B = int.from_bytes(B_bytes, "big")

        if self.B % N == 0:
            raise ValueError("Valeur B invalide reçue de l'accessoire (B % N == 0).")

        k = int.from_bytes(_sha512(pad(N), pad(G)), "big")

        self.x = int.from_bytes(
            _sha512(self.s, _sha512(self.username, b":", password)), "big"
        )

        A_bytes = pad(self.A)
        B_bytes_padded = pad(self.B)
        self.u = int.from_bytes(_sha512(A_bytes, B_bytes_padded), "big")
        if self.u == 0:
            raise ValueError("Scrambling parameter u == 0 (ne devrait pas arriver).")

        base = (self.B - k * pow(G, self.x, N)) % N
        exponent = self.a + self.u * self.x
        self.S = pow(base, exponent, N)

        self.K = _sha512(pad(self.S))

    def compute_client_proof(self) -> bytes:
        """M1 : preuve que nous connaissons le mot de passe (code à 8
        chiffres), à envoyer dans M3.

        Important : contrairement à k et u (qui utilisent PAD() jusqu'à
        N_BYTES), la formule de M1 utilise l'encodage big-endian MINIMAL
        de N, g, A et B — pas de remplissage. Pour g=5, ça veut dire un
        seul octet (0x05), pas 384. Voir _minimal_bytes() ci-dessus pour
        la source de cette distinction.
        """
        hN = int.from_bytes(_sha512(_minimal_bytes(N)), "big")
        hG = int.from_bytes(_sha512(_minimal_bytes(G)), "big")
        h_ng_xor = (hN ^ hG).to_bytes(64, "big")
        h_username = _sha512(self.username)
        return _sha512(
            h_ng_xor,
            h_username,
            self.s,
            _minimal_bytes(self.A),
            _minimal_bytes(self.B),
            self.K,
        )

    def verify_server_proof(self, server_proof: bytes) -> None:
        """Vérifie M2 (preuve de l'accessoire), reçue dans M4. Lève
        SrpAuthenticationError si elle ne correspond pas — le cas le plus
        probable est un code à 8 chiffres incorrect.

        Comme pour M1, A est encodé en big-endian minimal ici (pas PAD())."""
        client_proof = self.compute_client_proof()
        expected = _sha512(_minimal_bytes(self.A), client_proof, self.K)
        if not secrets.compare_digest(expected, server_proof):
            raise SrpAuthenticationError(
                "La preuve SRP de l'accessoire ne correspond pas. Cause la "
                "plus probable : le code à 8 chiffres saisi est incorrect."
            )
