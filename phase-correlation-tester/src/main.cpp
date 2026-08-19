#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>

#include "PhaseCorrelationEngine.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    QGuiApplication::setApplicationName(QStringLiteral("Phase Correlation Tester"));
    QGuiApplication::setOrganizationName(QStringLiteral("masterOfSeagull"));

    PhaseCorrelationEngine correlationEngine;

    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty(QStringLiteral("correlationEngine"), &correlationEngine);
    engine.loadFromModule("PhaseCorrelationTester", "Main");

    if (engine.rootObjects().isEmpty()) {
        return -1;
    }

    return app.exec();
}
