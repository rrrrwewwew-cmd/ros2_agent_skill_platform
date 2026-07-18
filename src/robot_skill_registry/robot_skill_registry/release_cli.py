"""CLI for Ed25519 Skill release key generation, signing, and recording."""

import argparse
import json
from pathlib import Path

from .registry import (
    RegistryConflictError,
    RegistryContractError,
    RegistryNotFoundError,
)
from .release_crypto import (
    canonical_json,
    create_signature_envelope,
    generate_ed25519_keypair,
    parse_signature_envelope,
    ReleaseSignatureError,
    verify_and_record_signature,
)


def _build_parser():
    parser = argparse.ArgumentParser(
        description='Create and verify hash-bound Ed25519 Skill releases.'
    )
    commands = parser.add_subparsers(dest='command', required=True)

    keygen = commands.add_parser('keygen')
    keygen.add_argument('--private-key', required=True)
    keygen.add_argument('--public-key', required=True)
    keygen.add_argument('--force', action='store_true')

    sign = commands.add_parser('sign')
    sign.add_argument('--repository-root', required=True)
    sign.add_argument('--name', required=True)
    sign.add_argument('--version', required=True)
    sign.add_argument('--artifact-hash', required=True)
    sign.add_argument('--private-key', required=True)
    sign.add_argument('--signer', required=True)
    sign.add_argument('--output', required=True)

    verify = commands.add_parser('verify-record')
    verify.add_argument('--db', required=True)
    verify.add_argument('--repository-root', required=True)
    verify.add_argument('--envelope', required=True)
    verify.add_argument('--public-key', required=True)
    verify.add_argument('--reason', required=True)
    return parser


def _print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv=None):
    """Run one explicit release operation without exposing private key data."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == 'keygen':
            result = generate_ed25519_keypair(
                args.private_key, args.public_key, overwrite=args.force,
            )
        elif args.command == 'sign':
            envelope = create_signature_envelope(
                args.repository_root,
                args.name,
                args.version,
                args.artifact_hash,
                args.private_key,
                args.signer,
            )
            output = Path(args.output).expanduser().resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                canonical_json(envelope) + '\n', encoding='utf-8'
            )
            result = {
                'envelope': str(output),
                'name': envelope['name'],
                'version': envelope['version'],
                'artifact_hash': envelope['artifact_hash'],
                'public_key_fingerprint': envelope['public_key_fingerprint'],
            }
        else:
            envelope = parse_signature_envelope(
                Path(args.envelope).expanduser().read_text(encoding='utf-8')
            )
            record = verify_and_record_signature(
                args.db,
                args.repository_root,
                envelope,
                args.public_key,
                args.reason,
            )
            result = {
                'verified': True,
                'name': record['name'],
                'version': record['version'],
                'artifact_hash': record['artifact_hash'],
                'state': record['state'],
                'signer': record['signer'],
            }
    except (
        OSError,
        RegistryConflictError,
        RegistryContractError,
        RegistryNotFoundError,
        ReleaseSignatureError,
    ) as exception:
        parser.exit(3, f'RELEASE ERROR: {exception}\n')
    _print_json(result)


if __name__ == '__main__':
    main()
