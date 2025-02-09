from enum import Enum
import argparse
import os
import shutil
import json
from json import JSONEncoder
from database import get_db, create_db, VestingModel, ProofModel
import sqlalchemy.orm as orm
from csv_parser import parse_vestings_csv
from proof_generator import generate_and_add_proof
from constants import *
from web3 import Web3


def prepare_db(db_file):
    print(80 * "-")
    print(f"Creating database")
    print(80 * "-")
    create_db(db_file)


def process_vestings(db: orm.Session, chain_id):
    parse_vestings_csv(db, "user", chain_id)
    parse_vestings_csv(db, "ecosystem", chain_id)


def generate_proofs(db: orm.Session, chain_id):
    generate_and_add_proof(db, "user", chain_id)
    generate_and_add_proof(db, "ecosystem", chain_id)


def export_data(db: orm.Session, chain_id, output_directory, export_type="snapshot"):
    class VestingData:
        def __init__(
                self,
                account,
                chainId,
                contract,
                vestingId,
                durationWeeks,
                startDate,
                amount,
                curve
        ):
            self.account = account
            self.chainId = chainId
            self.contract = contract
            self.vestingId = vestingId
            self.durationWeeks = durationWeeks
            self.startDate = startDate
            self.amount = amount
            self.curve = curve

    class VestingDataWithProof:
        def __init__(
                self,
                tag,
                account,
                chainId,
                contract,
                vestingId,
                durationWeeks,
                startDate,
                amount,
                curve,
                proof
        ):
            self.tag = tag
            self.account = account
            self.chainId = chainId
            self.contract = contract
            self.vestingId = vestingId
            self.durationWeeks = durationWeeks
            self.startDate = startDate
            self.amount = amount
            self.curve = curve
            self.proof = proof

    class VestingEncoder(JSONEncoder):
        def default(self, o):

            d = dict(o.__dict__)
            for k, v in list(d.items()):
                if v is None:
                    del d[k]

            return d

    def map_proof(proof):
        return HexBytes(proof.proof).hex()

    def map_vesting(model):
        vesting_data = VestingData(
            account=Web3.toChecksumAddress(model.owner),
            chainId=chain_id,
            contract=Web3.toChecksumAddress(ECOSYSTEM_AIRDROP_ADDRESS) if model.type == "ecosystem" else Web3.toChecksumAddress(USER_AIRDROP_ADDRESS),
            vestingId=model.vesting_id,
            durationWeeks=model.duration_weeks,
            startDate=model.start_date,
            amount=model.amount,
            curve=model.curve_type
        )
        return vesting_data

    def map_vesting_with_proof(model):
        vesting_data = VestingDataWithProof(
            tag=model.type,
            account=model.owner,
            chainId=chain_id,
            contract=Web3.toChecksumAddress(ECOSYSTEM_AIRDROP_ADDRESS) if model.type == "ecosystem" else Web3.toChecksumAddress(USER_AIRDROP_ADDRESS),
            vestingId=model.vesting_id,
            durationWeeks=model.duration_weeks,
            startDate=model.start_date,
            amount=model.amount,
            curve=model.curve_type,
            proof=list(map(map_proof, model.proofs))
        )
        return vesting_data

    print(80 * "-")
    print(f"Exporting vestings")
    print(80 * "-")

    if os.path.exists("../data/allocations"):
        shutil.rmtree("../data/allocations")

    if not os.path.exists("../data/allocations"):
        os.makedirs(f"../data/allocations/{chain_id}")

    vestings = list(
        map(
            map_vesting_with_proof if export_type == "snapshot" else map_vesting,
            db.query(VestingModel)
            .where(VestingModel.chain_id == chain_id)
            .order_by(VestingModel.owner)
        )
    )

    result = []

    i = 0
    while i < len(vestings):

        vesting_array = []

        vesting = vestings[i]

        print(f"Writing {vesting.account} vestings to file")

        vesting_array.append(vesting)

        j = i + 1
        while j < len(vestings) and vestings[j].account == vesting.account:
            vesting_array.append(vestings[j])
            j = j + 1

        if export_type == "snapshot":
            result.append(vesting_array)
        else:
            with open(f"{output_directory}/{vesting.account}.json", "w") as file:
                file.write(json.dumps(vesting_array, indent=4, cls=VestingEncoder))
        i = j

    if export_type == "snapshot":
        with open(f"{output_directory}/snapshot-allocations-data.json", "w") as file:
            file.write(json.dumps(result, indent=4, cls=VestingEncoder))


class Export(Enum):
    none = 'none'
    snapshot = 'snapshot'
    allocations = 'allocations'

    def __str__(self):
        return self.name

    @staticmethod
    def from_string(s):
        try:
            return Export[s]
        except KeyError:
            raise ValueError()

    @staticmethod
    def argparse(s):
        try:
            return Export[s.upper()]
        except KeyError:
            return s


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Vesting data converter and exporter.')

    parser.add_argument(
        '--chain-id',
        dest='chain_id',
        help='chain id'
    )

    parser.add_argument(
        '--output-directory',
        dest='output_dir',
        default='../data/allocations',
        help='output directory',
        required=True
    )

    parser.add_argument(
        '--db-file',
        dest='db_file',
        action='store_const',
        const='allocations.db',
        required=False,
        help='path to a database file'
    )

    parser.add_argument(
        '--clear-db',
        dest='clear_db',
        action='store_const',
        const=True,
        default=False,
        help='clear database',
        required=False
    )

    parser.add_argument(
        '--process-vestings',
        dest='process_vestings',
        action='store_const',
        const=True,
        default=False,
        help='process vestings',
        required=False
    )

    parser.add_argument(
        '--generate-proofs',
        dest='process_vestings',
        action='store_const',
        const=True,
        default=False,
        help='generate proofs',
        required=False
    )

    parser.add_argument(
        '--export',
        type=Export.argparse,
        choices=list(Export),
        dest='export',
        default=Export.none,
        help='export type (default none)',
        required=False
    )

    args = parser.parse_args()

    if args.clear_db:
        if os.path.exists(args.db_file):
            os.remove(args.db_file)
        prepare_db(args.db_file)

    if not os.path.exists(args.db_file):
        prepare_db(args.db_file)

    db = next(get_db(args.db_file))

    if args.process_vestings:
        process_vestings(db, args.chain_id)

    if args.generate_proofs:
        generate_proofs(db, args.chain_id)

    if args.export != "none":
        export_data(db, args.chain_id, args.output_directory, args.export)
