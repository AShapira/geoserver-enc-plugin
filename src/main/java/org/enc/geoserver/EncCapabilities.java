package org.enc.geoserver;

import java.io.*;
import java.util.HashSet;
import java.util.Set;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilderFactory;
import javax.xml.transform.TransformerFactory;
import javax.xml.transform.dom.DOMSource;
import javax.xml.transform.stream.StreamResult;
import org.geoserver.catalog.*;
import org.geoserver.ows.*;
import org.geoserver.platform.Operation;
import org.w3c.dom.*;

/** Identify ENC entries in the capabilities document produced for this caller. */
public final class EncCapabilities extends AbstractDispatcherCallback {
    private static final String ENC = "urn:geoserver:enc:viewer:1";
    private static final String WMS = "http://www.opengis.net/wms";
    private final Catalog catalog;

    public EncCapabilities(Catalog catalog) {
        this.catalog = catalog;
    }

    @Override
    public Response responseDispatched(Request request, Operation operation, Object result, Response response) {
        if (!"WMS".equalsIgnoreCase(request.getService()) || !"GetCapabilities".equalsIgnoreCase(request.getRequest())
                || !"1.3.0".equals(request.getVersion()) || request.getRawKvp() == null
                || !"true".equalsIgnoreCase(String.valueOf(request.getRawKvp().get("ENCDISCOVERY")))) {
            return response;
        }
        return new Response(response.getBinding()) {
            @Override public String getMimeType(Object value, Operation op) { return response.getMimeType(value, op); }
            @Override public String[][] getHeaders(Object value, Operation op) { return response.getHeaders(value, op); }
            @Override public void write(Object value, OutputStream out, Operation op) throws IOException {
                var bytes = new ByteArrayOutputStream();
                response.write(value, bytes, op);
                if (bytes.size() == 0) return;
                annotate(new ByteArrayInputStream(bytes.toByteArray()), out);
            }
        };
    }

    private void annotate(InputStream input, OutputStream output) throws IOException {
        try {
            var factory = DocumentBuilderFactory.newDefaultNSInstance();
            factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
            var document = factory.newDocumentBuilder().parse(input);
            Element root = document.getDocumentElement();
            root.setAttributeNS(XMLConstants.XMLNS_ATTRIBUTE_NS_URI, "xmlns:enc", ENC);
            root.setAttributeNS(ENC, "enc:discovery", "1");
            var layers = root.getElementsByTagNameNS(WMS, "Layer");
            for (int i = 0; i < layers.getLength(); i++) annotateLayer((Element) layers.item(i));
            var transformer = TransformerFactory.newDefaultInstance().newTransformer();
            transformer.transform(new DOMSource(document), new StreamResult(output));
        } catch (javax.xml.parsers.ParserConfigurationException | org.xml.sax.SAXException
                 | javax.xml.transform.TransformerException e) {
            throw new IOException("Could not annotate WMS capabilities", e);
        }
    }

    private void annotateLayer(Element element) {
        for (Node child = element.getFirstChild(); child != null; child = child.getNextSibling()) {
            if (!"Name".equals(child.getLocalName()) || !WMS.equals(child.getNamespaceURI())) continue;
            String name = child.getTextContent();
            WorkspaceInfo workspace = LocalWorkspace.get();
            String qualified = workspace != null && !name.contains(":") ? workspace.getName() + ":" + name : name;
            LayerInfo layer = catalog.getLayerByName(qualified);
            if (layer != null) {
                StoreInfo store = encStore(layer);
                if (store != null) {
                    element.setAttributeNS(ENC, "enc:kind", "layer");
                    element.setAttributeNS(ENC, "enc:store", store.getName());
                    element.setAttributeNS(ENC, "enc:workspace", store.getWorkspace().getName());
                }
            } else {
                LayerGroupInfo group = catalog.getLayerGroupByName(qualified);
                if (group != null && entirelyEnc(group, new HashSet<>())) {
                    element.setAttributeNS(ENC, "enc:kind", "group");
                }
            }
            return;
        }
    }

    private static StoreInfo encStore(LayerInfo layer) {
        if (layer.getResource() instanceof FeatureTypeInfo && layer.getResource().getStore() instanceof DataStoreInfo store
                && "s57".equals(store.getConnectionParameters().get("dbtype"))) return store;
        return null;
    }

    private static boolean entirelyEnc(PublishedInfo info, Set<String> ancestors) {
        if (info instanceof LayerInfo layer) return encStore(layer) != null;
        if (!(info instanceof LayerGroupInfo group) || !ancestors.add(group.getId())) return false;
        try {
            if (group.getRootLayer() != null && encStore(group.getRootLayer()) == null) return false;
            if (group.getLayers().isEmpty() || !group.getLayers().stream().allMatch(child -> entirelyEnc(child, ancestors))) {
                return false;
            }
            return group.getLayerGroupStyles().stream().flatMap(style -> style.getLayers().stream())
                    .allMatch(child -> entirelyEnc(child, ancestors));
        } finally {
            ancestors.remove(group.getId());
        }
    }
}
