from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import customtkinter as ctk
from PIL import Image
import pypdfium2
from reportlab.pdfgen import canvas
import local_reviews as reviews
from visual_pages import load_visual,visual_page,fitted_rect,normalized_point
from visual_review_ui import VisualReviewDialog
from ui_dispatch import cancel_widget_callbacks


class VisualReviewTests(unittest.TestCase):
    def test_pdf_pages_and_coordinate_mapping(self):
        with tempfile.TemporaryDirectory() as td:
            source=Path(td)/'brief.pdf';pdf=canvas.Canvas(str(source));pdf.drawString(30,700,'Page one');pdf.showPage();pdf.drawString(30,700,'Page two');pdf.save()
            document=load_visual(source);self.assertEqual(document['count'],2);self.assertIsNotNone(visual_page(document,1));self.assertIsNone(visual_page(document,2))
            rect=fitted_rect((1000,500),500,500);self.assertEqual(normalized_point(rect,250,250),(.5,.5));self.assertIsNone(normalized_point(rect,0,0))

    def test_invalid_pin_is_rejected_and_valid_pin_stays_on_its_version(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'design.png';Image.new('RGB',(600,400),'red').save(source)
            path=reviews.create_review('Launch',[source],directory=root/'reviews');asset=reviews.load_review(path)['assets'][0];version=asset['versions'][0]
            with self.assertRaisesRegex(ValueError,'location'):reviews.add_comment(path,asset['id'],version['id'],'Reviewer','Bad',{'page':0,'x':.5,'y':.5})
            reviews.add_comment(path,asset['id'],version['id'],'Reviewer','Move this logo',{'page':1,'x':.2,'y':.7})
            reviews.add_revision(path,asset['id'],source);versions=reviews.load_review(path)['assets'][0]['versions']
            self.assertEqual(versions[0]['comments'][0]['anchor'],{'page':1,'x':.2,'y':.7});self.assertFalse(versions[1]['comments'])

    def test_native_ui_comparison_and_pin_comment(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td);source=folder/'design.png';Image.new('RGB',(600,400),'red').save(source)
            path=reviews.create_review('Launch',[source],directory=folder/'reviews');asset=reviews.load_review(path)['assets'][0]
            Image.new('RGB',(600,400),'blue').save(source);reviews.add_revision(path,asset['id'],source);asset=reviews.load_review(path)['assets'][0]
            root=ctk.CTk();root.withdraw();dialog=VisualReviewDialog(root,path,asset['id'],asset['versions'][-1]['id'],'Reviewer')
            def wait(condition):
                deadline=time.monotonic()+8
                while not condition() and time.monotonic()<deadline:root.update();time.sleep(.02)
                self.assertTrue(condition())
            try:
                wait(lambda:dialog._images[0] is not None and dialog._rects[0] is not None)
                dialog.choose_compare(next(label for label,value in dialog.compare_options.items() if value))
                wait(lambda:all(image is not None for image in dialog._images))
                self.assertEqual(dialog._images[0].getpixel((0,0)),(0,0,255));self.assertEqual(dialog._images[1].getpixel((0,0)),(255,0,0))
                left,top,width,height=dialog._rects[0];dialog.pin(SimpleNamespace(x=left+width*.3,y=top+height*.4));dialog.text.insert('1.0','Move this element.');dialog.add_comment()
                wait(lambda:not dialog._busy)
                comment=reviews.load_review(path)['assets'][0]['versions'][-1]['comments'][0]
                self.assertAlmostEqual(comment['anchor']['x'],.3,delta=.003);self.assertAlmostEqual(comment['anchor']['y'],.4,delta=.003)
                dialog.zoom.set('200%');dialog.reset_view();root.update()
                canvas=dialog.canvases[0];canvas.xview_moveto(.3);canvas.yview_moveto(.2);root.update()
                left,top,width,height=dialog._rects[0]
                x,y=100,100
                expected=normalized_point(dialog._rects[0],canvas.canvasx(x),canvas.canvasy(y))
                self.assertIsNotNone(expected);dialog.pin(SimpleNamespace(x=x,y=y))
                self.assertAlmostEqual(dialog.anchor['x'],expected[0]);self.assertAlmostEqual(dialog.anchor['y'],expected[1])
            finally:dialog.destroy();cancel_widget_callbacks(root);root.destroy()
