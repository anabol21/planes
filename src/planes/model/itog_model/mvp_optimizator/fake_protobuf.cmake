# fake_protobuf.cmake
if(NOT TARGET protobuf::libprotobuf)
    add_library(protobuf::libprotobuf UNKNOWN IMPORTED)
    set_target_properties(protobuf::libprotobuf PROPERTIES
        IMPORTED_LOCATION "/opt/conda/lib/libprotobuf.so"
        INTERFACE_INCLUDE_DIRECTORIES "/opt/conda/include"
    )
endif()