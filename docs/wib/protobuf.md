# Protobuf source files for the DUNE HD and VD/BDE WIB

The generated `archive/wib/protobuf/wib_pb2.py` uses `libprotoc 36.2`
(Python generator 7.36.2). Use `uv sync --locked` for a compatible runtime;
protobuf 7.36.2 or newer is required. The old generated code from protoc 3.14
fails with the current runtime with `Descriptors cannot be created directly`.

To regenerate from the repository root, use the same compiler version:

```bash
protoc --version  # libprotoc 36.2
protoc --proto_path=archive/wib/protobuf --python_out=archive/wib/protobuf archive/wib/protobuf/wib.proto
```

Do not edit the generated Python file by hand. The `.proto` defines the
message fields and wire format; regeneration updates the Python binding.

