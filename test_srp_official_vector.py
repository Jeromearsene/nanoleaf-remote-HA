"""
Test de non-régression permanent pour hapble/srp.py, basé sur le vecteur de
test OFFICIEL publié dans la spécification HAP (Release R2, section 5.5.2
"SRP Test Vectors").

Les valeurs sont chargées depuis test_vectors.json, lui-même reconstruit
programmatiquement à partir du texte brut de la spec (blocs hex copiés tels
quels, espaces retirés par script) — pas retapées à la main, pour éviter la
même classe d'erreur que le bug de transcription détecté plus tôt dans la
constante N du groupe SRP.

Un succès ici est un signal plus fort qu'un test contre notre propre faux
accessoire : il prouve la conformité à un vecteur publié par Apple elle-même,
pas seulement notre cohérence interne.
"""

import json
from pathlib import Path

from hapble import srp

VECTORS_PATH = Path(__file__).parent / "test_vectors.json"

I = b"alice"
P = b"password123"


def _h(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr)


def test_official_srp_vector() -> None:
    tv = json.loads(VECTORS_PATH.read_text())

    a = int(tv["a_private"], 16)
    b = int(tv["b_private"], 16)
    salt = _h(tv["salt"])

    # --- x et v (verifier) --------------------------------------------
    x = int.from_bytes(srp._sha512(salt, srp._sha512(I, b":", P)), "big")
    v = pow(srp.G, x, srp.N)
    assert v == int(tv["v"], 16), "Verifier v incorrect"
    print("OK : verifier (v) correct")

    # --- A et B (clés publiques) ------------------------------------------
    A = pow(srp.G, a, srp.N)
    assert A == int(tv["A_public"], 16), "Clé publique A incorrecte"
    print("OK : clé publique A correcte")

    k = int.from_bytes(srp._sha512(srp.pad(srp.N), srp.pad(srp.G)), "big")
    B = (k * v + pow(srp.G, b, srp.N)) % srp.N
    assert B == int(tv["B_public"], 16), "Clé publique B incorrecte"
    print("OK : clé publique B correcte (confirme aussi la formule de k)")

    # --- S et K, via notre VRAIE implémentation (SrpClient) ----------------
    # Ce vecteur générique utilise le username "alice", pas "Pair-Setup"
    # (celui que HAP utilise réellement) — on l'indique explicitement.
    client = srp.SrpClient(username=I)
    client.a = a
    client.A = A
    client.process_challenge(salt, srp.pad(B), P)

    assert client.S == int(tv["S"], 16), "Secret partagé S incorrect"
    print("OK : secret partagé (S) correct")

    assert client.K == _h(tv["K"]), "Clé de session K incorrecte"
    print("OK : clé de session (K) correcte")

    print()
    print(
        "Vecteur de test officiel HAP (spec R2, §5.5.2) : TOUS LES "
        "CHAMPS CORRESPONDENT (v, A, B, S, K)."
    )


def cli() -> None:
    """Point d'entrée synchrone, pour `poetry run` (voir pyproject.toml)."""
    test_official_srp_vector()


if __name__ == "__main__":
    cli()
