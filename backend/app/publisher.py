import asyncio

from app.modules.publishing_worker import scheduled_publisher_loop


def main() -> None:
    asyncio.run(scheduled_publisher_loop())


if __name__ == "__main__":
    main()