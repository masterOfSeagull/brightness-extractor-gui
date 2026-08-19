#pragma once

#include <QObject>
#include <QUrl>
#include <QVariantList>

#include <opencv2/core.hpp>

class PhaseCorrelationEngine final : public QObject
{
    Q_OBJECT

    Q_PROPERTY(QString imageAUrl READ imageAUrl NOTIFY imageAChanged)
    Q_PROPERTY(QString imageBUrl READ imageBUrl NOTIFY imageBChanged)
    Q_PROPERTY(QString heatmapUrl READ heatmapUrl NOTIFY resultChanged)
    Q_PROPERTY(QString statusMessage READ statusMessage NOTIFY statusChanged)
    Q_PROPERTY(QVariantList peaks READ peaks NOTIFY resultChanged)
    Q_PROPERTY(double runtimeMs READ runtimeMs NOTIFY resultChanged)
    Q_PROPERTY(bool hasResult READ hasResult NOTIFY resultChanged)

    Q_PROPERTY(bool hannWindow READ hannWindow WRITE setHannWindow NOTIFY settingsChanged)
    Q_PROPERTY(bool limitSearch READ limitSearch WRITE setLimitSearch NOTIFY settingsChanged)
    Q_PROPERTY(int maxDx READ maxDx WRITE setMaxDx NOTIFY settingsChanged)
    Q_PROPERTY(int maxDy READ maxDy WRITE setMaxDy NOTIFY settingsChanged)
    Q_PROPERTY(int peakCount READ peakCount WRITE setPeakCount NOTIFY settingsChanged)
    Q_PROPERTY(int suppressionRadius READ suppressionRadius WRITE setSuppressionRadius NOTIFY settingsChanged)

public:
    explicit PhaseCorrelationEngine(QObject *parent = nullptr);

    QString imageAUrl() const { return m_imageAUrl; }
    QString imageBUrl() const { return m_imageBUrl; }
    QString heatmapUrl() const { return m_heatmapUrl; }
    QString statusMessage() const { return m_statusMessage; }
    QVariantList peaks() const { return m_peaks; }
    double runtimeMs() const { return m_runtimeMs; }
    bool hasResult() const { return m_hasResult; }

    bool hannWindow() const { return m_hannWindow; }
    bool limitSearch() const { return m_limitSearch; }
    int maxDx() const { return m_maxDx; }
    int maxDy() const { return m_maxDy; }
    int peakCount() const { return m_peakCount; }
    int suppressionRadius() const { return m_suppressionRadius; }

    Q_INVOKABLE bool setImageA(const QUrl &url);
    Q_INVOKABLE bool setImageB(const QUrl &url);
    Q_INVOKABLE void analyze();

    void setHannWindow(bool value);
    void setLimitSearch(bool value);
    void setMaxDx(int value);
    void setMaxDy(int value);
    void setPeakCount(int value);
    void setSuppressionRadius(int value);

signals:
    void imageAChanged();
    void imageBChanged();
    void resultChanged();
    void statusChanged();
    void settingsChanged();

private:
    struct Peak {
        double dx = 0.0;
        double dy = 0.0;
        double value = 0.0;
        double relative = 0.0;
        cv::Point integerLocation;
    };

    static bool loadGrayFloat(const QUrl &url, cv::Mat &out, QString &error);
    static void fftShift(cv::Mat &matrix);
    static double subpixelOffset(double left, double center, double right);

    QList<Peak> detectPeaks(const cv::Mat &correlation) const;
    bool writeHeatmap(const cv::Mat &correlation, const QList<Peak> &peaks, QString &outputUrl, QString &error);
    void setStatus(const QString &message);
    void clearResult();

    QString m_imageAUrl;
    QString m_imageBUrl;
    QString m_heatmapUrl;
    QString m_statusMessage = QStringLiteral("Load two images to begin.");
    QVariantList m_peaks;
    double m_runtimeMs = 0.0;
    bool m_hasResult = false;

    bool m_hannWindow = true;
    bool m_limitSearch = false;
    int m_maxDx = 128;
    int m_maxDy = 128;
    int m_peakCount = 5;
    int m_suppressionRadius = 12;
    quint64 m_revision = 0;
};
