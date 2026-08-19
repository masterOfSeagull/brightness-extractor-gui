cmake_minimum_required(VERSION 3.21)

project(PhaseCorrelationTester VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Qt6 6.5 REQUIRED COMPONENTS Quick QuickControls2)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)

qt_standard_project_setup(REQUIRES 6.5)

qt_add_executable(phase-correlation-tester
    src/main.cpp
    src/PhaseCorrelationEngine.cpp
    src/PhaseCorrelationEngine.h
)

qt_add_qml_module(phase-correlation-tester
    URI PhaseCorrelationTester
    VERSION 1.0
    QML_FILES
        qml/Main.qml
)

target_include_directories(phase-correlation-tester PRIVATE
    src
    ${OpenCV_INCLUDE_DIRS}
)

target_link_libraries(phase-correlation-tester PRIVATE
    Qt6::Quick
    Qt6::QuickControls2
    ${OpenCV_LIBS}
)

if(WIN32)
    set_target_properties(phase-correlation-tester PROPERTIES WIN32_EXECUTABLE TRUE)
endif()
