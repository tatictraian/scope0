#!/usr/bin/env python3
"""Initialize FGA authorization model and seed default tuples.

Usage:
    python scripts/fga_init.py <user_id>

Where <user_id> is the Auth0 user sub (e.g., auth0|abc123).

FGA model supports:
- Tool categories (read_tools, write_tools) with can_use_category relation
- Individual tool overrides via direct can_use relation
- Agent self-restriction via tuple deletion (one-directional)

Default: read_tools category enabled, write_tools category disabled.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from openfga_sdk import (
    ClientConfiguration,
    OpenFgaClient,
)
from openfga_sdk.client.models import ClientTuple
from openfga_sdk import WriteAuthorizationModelRequest
from openfga_sdk.credentials import CredentialConfiguration, Credentials
from openfga_sdk.models import (
    Metadata,
    RelationMetadata,
    RelationReference,
    TypeDefinition,
    Userset,
)


def get_fga_config() -> ClientConfiguration:
    return ClientConfiguration(
        api_url=os.getenv("FGA_API_URL", "https://api.us1.fga.dev"),
        store_id=os.getenv("FGA_STORE_ID"),
        credentials=Credentials(
            method="client_credentials",
            configuration=CredentialConfiguration(
                api_issuer=os.getenv("FGA_API_TOKEN_ISSUER", "auth.fga.dev"),
                api_audience=os.getenv("FGA_API_AUDIENCE", "https://api.us1.fga.dev/"),
                client_id=os.getenv("FGA_CLIENT_ID"),
                client_secret=os.getenv("FGA_CLIENT_SECRET"),
            ),
        ),
    )


# Category → tools mapping
CATEGORIES = {
    "read_tools": [
        "scanGitHubExposure",
        "scanGoogleExposure",
        "scanSlackExposure",
        "listPullRequests",
        "searchEmails",
        "listCalendarEvents",
        "listSlackChannels",
    ],
    "write_tools": [
        "createIssue",
        "sendEmail",
    ],
}

# Categories enabled by default
DEFAULT_ENABLED_CATEGORIES = ["read_tools"]


async def write_model(client: OpenFgaClient) -> str:
    """Write the FGA authorization model with tool categories. Returns model ID."""
    model = WriteAuthorizationModelRequest(
        schema_version="1.1",
        type_definitions=[
            TypeDefinition(
                type="user",
                relations={},
            ),
            TypeDefinition(
                type="tool_category",
                relations={
                    "can_use_category": Userset(this={}),
                },
                metadata=Metadata(
                    relations={
                        "can_use_category": RelationMetadata(
                            directly_related_user_types=[
                                RelationReference(type="user"),
                            ]
                        ),
                    }
                ),
            ),
            TypeDefinition(
                type="tool",
                relations={
                    "can_use": Userset(this={}),
                    "in_category": Userset(this={}),
                },
                metadata=Metadata(
                    relations={
                        "can_use": RelationMetadata(
                            directly_related_user_types=[
                                RelationReference(type="user"),
                            ]
                        ),
                        "in_category": RelationMetadata(
                            directly_related_user_types=[
                                RelationReference(type="tool_category"),
                            ]
                        ),
                    }
                ),
            ),
        ],
    )
    response = await client.write_authorization_model(model)
    model_id = response.authorization_model_id
    print(f"Authorization model created: {model_id}")
    return model_id


async def seed_tuples(client: OpenFgaClient, user_id: str) -> None:
    """Seed default FGA tuples."""
    tuples = []

    # Category memberships (tool → category)
    for cat_name, tool_names in CATEGORIES.items():
        for tool_name in tool_names:
            tuples.append(
                ClientTuple(
                    user=f"tool_category:{cat_name}",
                    relation="in_category",
                    object=f"tool:{tool_name}",
                )
            )

    # Default category access for user
    for cat_name in DEFAULT_ENABLED_CATEGORIES:
        tuples.append(
            ClientTuple(
                user=f"user:{user_id}",
                relation="can_use_category",
                object=f"tool_category:{cat_name}",
            )
        )

    # Individual tool access for read tools (direct can_use tuples)
    # This is what fga_tool_auth checks — direct user:can_use:tool relation
    for tool_name in CATEGORIES["read_tools"]:
        tuples.append(
            ClientTuple(
                user=f"user:{user_id}",
                relation="can_use",
                object=f"tool:{tool_name}",
            )
        )

    # Write tools NOT seeded — disabled by default

    if tuples:
        # Write in batches (FGA has per-request limits)
        batch_size = 10
        for i in range(0, len(tuples), batch_size):
            batch = tuples[i : i + batch_size]
            await client.write_tuples(batch)

        print(f"Seeded {len(tuples)} tuples for user:{user_id}")
        print(f"  Categories: {', '.join(CATEGORIES.keys())}")
        print(f"  Enabled categories: {', '.join(DEFAULT_ENABLED_CATEGORIES)}")
        print(f"  Enabled tools (direct): {', '.join(CATEGORIES['read_tools'])}")
        print(f"  Disabled (default): {', '.join(CATEGORIES['write_tools'])}")


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/fga_init.py <user_id>")
        print("  user_id: Auth0 user sub (e.g., auth0|abc123)")
        sys.exit(1)

    user_id = sys.argv[1]
    config = get_fga_config()

    print(f"FGA Store: {config.store_id}")
    print(f"FGA API: {config.api_url}")
    print()

    async with OpenFgaClient(config) as client:
        model_id = await write_model(client)
        await seed_tuples(client, user_id)

    print()
    print("Done. Add this to your .env:")
    print(f'  FGA_MODEL_ID="{model_id}"')


if __name__ == "__main__":
    asyncio.run(main())
