package org.enc.geoserver;

import java.io.*;
import org.geoserver.config.GeoServer;
import org.geoserver.catalog.Catalog;
import org.geoserver.ows.ClasspathPublisher;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.web.servlet.handler.SimpleUrlHandlerMapping;
import org.springframework.context.ApplicationEvent;
import org.springframework.context.annotation.*;
import org.springframework.context.event.SmartApplicationListener;
import org.springframework.core.type.AnnotatedTypeMetadata;
import org.springframework.util.ClassUtils;

/** Spring Boot entry point for GeoServer Cloud services, which do not import plugin XML. */
@Configuration(proxyBeanMethods=false)
public class CloudPortrayalConfiguration {
    @Bean
    SmartApplicationListener encCloudStyleInstallation(GeoServer server) {
        return new SmartApplicationListener() {
            @Override public boolean supportsEventType(Class<? extends ApplicationEvent> type) {
                // Cloud creates child contexts when the event bus binds. Install once the
                // Boot application is ready, after the catalogue and bus have started.
                return type.getName().equals("org.springframework.boot.context.event.ApplicationReadyEvent");
            }
            @Override public void onApplicationEvent(ApplicationEvent event) {
                if (Boolean.getBoolean("enc.installStyles")) {
                    try { new StyleLibraryInstaller().initialize(server); }
                    catch (IOException e) { throw new UncheckedIOException(e); }
                }
            }
        };
    }

    @Configuration(proxyBeanMethods=false)
    @Conditional(HasWms.class)
    static class Rendering {
        @Bean EncCapabilities encCapabilities(@Qualifier("localWorkspaceCatalog") Catalog catalog) {
            return new EncCapabilities(catalog);
        }
        @Bean ClasspathPublisher encViewerPublisher() {
            return new ClasspathPublisher(EncCapabilities.class);
        }
        @Bean SimpleUrlHandlerMapping encViewerMapping(@Qualifier("encViewerPublisher") ClasspathPublisher publisher) {
            return new SimpleUrlHandlerMapping(java.util.Map.of(
                    "/enc/viewer/index.html", publisher, "/enc/viewer/viewer.css", publisher,
                    "/enc/viewer/viewer.js", publisher), -60);
        }
        @Bean CatalogueScaleCallback encCloudCatalogueScaleCallback() { return new CatalogueScaleCallback(); }
    }
    static class HasWms implements Condition {
        public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
            return ClassUtils.isPresent("org.geoserver.wms.GetMapCallbackAdapter",context.getClassLoader());
        }
    }
}
