"""Local CONNECT proxy: HTTPS to public YouTube addresses only."""
import asyncio
import ipaddress
import re
import socket


def allowed(host):
    return bool(re.fullmatch(r"(?:[a-z0-9-]+\.)*(?:youtube\.com|googlevideo\.com|ytimg\.com|youtubei\.googleapis\.com|jnn-pa\.googleapis\.com)", host))


async def handle(reader, writer):
    remote = None
    try:
        request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
        line = request.split(b"\r\n", 1)[0].decode("ascii")
        method, target, _ = line.split(" ", 2)
        host, port = target.rsplit(":", 1)
        if method != "CONNECT" or port != "443" or not allowed(host):
            writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await writer.drain()
            return
        addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        address = next((item[4][0] for item in addresses if ipaddress.ip_address(item[4][0]).is_global), None)
        if not address:
            raise ValueError("No public address found")
        upstream, remote = await asyncio.wait_for(asyncio.open_connection(address, 443), 15)
        writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        await writer.drain()

        async def relay(source, destination):
            while data := await source.read(65536):
                destination.write(data)
                await destination.drain()

        tasks = [asyncio.create_task(relay(reader, remote)), asyncio.create_task(relay(upstream, writer))]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (Exception, asyncio.CancelledError):
        pass
    finally:
        if remote:
            remote.close()
        writer.close()
        await writer.wait_closed()


async def main():
    server = await asyncio.start_server(handle, "127.0.0.1", 18769, limit=8192)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
