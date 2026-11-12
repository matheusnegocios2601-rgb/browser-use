"""Gera os JSONs embarcados no app a partir dos dados TACO + IBGE.

Entrada: JSON extraído do pacote npm `taco-br-mcp@0.2.0` (dados TACO 4ª ed. NEPA/UNICAMP
e medidas caseiras IBGE POF 2008-2009, já conferidos célula a célula pelo projeto).
Extração sem executar código do pacote: ver `tools/jslit.py`.

Uso:
    npm pack taco-br-mcp@0.2.0 && tar xzf taco-br-mcp-0.2.0.tgz
    python3 -I tools/jslit.py package/dist/server.js taco_raw.json
    python3 -I tools/build_data.py taco_raw.json Sources/GarfadaCore/Resources
"""

import json
import sys
from pathlib import Path

# Rótulo do classificador da Apple (VNClassifyImageRequest, revisão 1) -> (nome em PT, ids TACO).
# Só rótulos que existem literalmente na lista oficial de 1303 identificadores.
# O primeiro id é a opção pré-selecionada; o usuário pode trocar.
# Lista vazia = o alimento existe no classificador mas NÃO existe na TACO (o app avisa e não inventa).
LABELS: dict[str, tuple[str, list[int]]] = {
	'almond': ('Amêndoa', [587]),
	'apple': ('Maçã', [222, 221]),
	'arugula': ('Rúcula', [152]),
	'avocado': ('Abacate', [163]),
	'bacon': ('Bacon / toucinho', [445, 444]),
	'banana': ('Banana', [182, 179, 178, 177, 180, 175]),
	'bean': ('Feijão', [561, 567, 563, 565, 569, 571, 573]),
	'beef': ('Carne bovina', [346, 344, 358, 370, 377, 383, 381, 368, 326, 363]),
	'beer': ('Cerveja', [474]),
	'beet': ('Beterraba', [97, 98]),
	'bell_pepper': ('Pimentão', [144, 145, 143]),
	'biscuit': ('Biscoito', [8, 13, 9, 10]),
	'birthday_cake': ('Bolo', [16, 17, 18, 15]),
	'bread': ('Pão', [53, 52, 54, 48, 51, 63]),
	'broccoli': ('Brócolis', [100, 101]),
	'butter': ('Manteiga', [261, 262]),
	'cake': ('Bolo', [16, 17, 18, 15]),
	'cake_regular': ('Bolo', [16, 17, 18, 15]),
	'cantaloupe': ('Melão', [236]),
	'carrot': ('Cenoura', [109, 110]),
	'cashew': ('Castanha-de-caju', [588]),
	'cauliflower': ('Couve-flor', [118, 117]),
	'celery': ('Aipo / salsão', [76]),
	'cereal': ('Cereal matinal', [25, 26, 22]),
	'cheese': ('Queijo', [463, 467, 461, 462, 464, 465, 469, 468]),
	'chives': ('Cebolinha', [108]),
	'chocolate': ('Chocolate', [495, 498, 496]),
	'citrus_fruit': ('Laranja', [214, 208, 216, 210, 212]),
	'coconut': ('Coco', [590, 591]),
	'coffee': ('Café (infusão)', [471]),
	'cookie': ('Biscoito', [8, 9, 10, 13]),
	'corn': ('Milho verde', [44, 45]),
	'crab': ('Caranguejo', [287]),
	'cucumber': ('Pepino', [142]),
	'daikon': ('Nabo', [137]),
	'egg': ('Ovo', [488, 490, 489]),
	'eggplant': ('Berinjela', [95, 96]),
	'fig': ('Figo', [194]),
	'fish': ('Peixe', [301, 307, 276, 313, 317, 318]),
	'fried_chicken': ('Frango à milanesa (mais próximo na TACO)', [401]),
	'fried_egg': ('Ovo frito', [490]),
	'fries': ('Batata frita', [93, 132, 90]),
	'garlic': ('Alho', [82]),
	'grape': ('Uva', [256, 257]),
	'green_beans': ('Vagem', [162]),
	'grilled_chicken': ('Frango grelhado/assado', [410, 408, 406, 396, 403]),
	'guava': ('Goiaba', [200, 197]),
	'ham': ('Presunto', [439, 438, 323]),
	'hamburger': ('Hambúrguer (só a carne; pão não incluso)', [417, 416]),
	'honey': ('Mel', [507]),
	'honeydew': ('Melão', [236]),
	'juice': ('Suco', [215, 209, 217, 211, 213, 252, 258]),
	'kiwi': ('Kiwi', [207]),
	'leek': ('Alho-poró', [83]),
	'lemon': ('Limão', [220, 219, 218]),
	'lettuce': ('Alface', [78, 79, 77, 80]),
	'lime': ('Limão', [220, 219, 218]),
	'mandarine': ('Tangerina / mexerica', [251, 238, 237]),
	'mango': ('Manga', [231, 228, 229]),
	'meat': ('Carne bovina', [346, 344, 358, 370, 377, 383, 381, 368, 326, 363]),
	'meatball': ('Almôndega', [331, 330]),
	'melon': ('Melão', [236]),
	'nut': ('Castanhas / nozes', [597, 589, 588, 587]),
	'omelet': ('Omelete de queijo', [484]),
	'onion': ('Cebola', [107]),
	'oranges': ('Laranja', [214, 208, 216, 210, 212]),
	'papaya': ('Mamão', [226, 225]),
	'passionfruit': ('Maracujá', [232]),
	'pasta': ('Macarrão', [542, 37]),
	'pea': ('Ervilha', [560, 559]),
	'peach': ('Pêssego', [244, 245]),
	'peanut': ('Amendoim', [558, 557]),
	'pear': ('Pêra', [243, 242]),
	'pepper_veggie': ('Pimentão', [144, 145, 143]),
	'persimmon': ('Caqui', [189]),
	'pineapple': ('Abacaxi', [164]),
	'plum': ('Ameixa', [172]),
	'pomegranate': ('Romã', [249]),
	'popcorn': ('Pipoca', [61]),
	'potato': ('Batata', [91, 93, 94, 88]),
	'poultry': ('Frango', [410, 408, 406, 396, 403]),
	'pumpkin': ('Abóbora', [64, 68]),
	'radish': ('Rabanete', [148]),
	'rice': ('Arroz', [3, 1, 5]),
	'salad': ('Salada', [78, 157, 546, 545]),
	'salami': ('Salame', [443]),
	'salmon': ('Salmão', [317, 316, 315]),
	'sardine': ('Sardinha', [318, 320, 319, 321]),
	'sausage': ('Linguiça', [423, 422, 420, 419]),
	'seafood': ('Camarão', [284, 286]),
	'sesame': ('Gergelim', [593]),
	'shellfish': ('Camarão', [284, 286]),
	'shellfish_prepared': ('Camarão', [284, 286]),
	'soda': ('Refrigerante', [480, 481, 482, 483]),
	'spaghetti': ('Macarrão', [542, 37]),
	'spareribs': ('Costela', [430, 347]),
	'spinach': ('Espinafre', [120, 119]),
	'starfruit': ('Carambola', [190]),
	'steak': ('Bife', [346, 344, 358, 370, 383, 381, 377, 368]),
	'strawberry': ('Morango', [239]),
	'sugar_cube': ('Açúcar', [494]),
	'tabbouleh': ('Tabule', [549]),
	'taro': ('Inhame', [126]),
	'tea_drink': ('Chá', [477, 476, 475]),
	'tomato': ('Tomate', [157]),
	'tuna': ('Atum', [277, 278]),
	'watermelon': ('Melancia', [235]),
	'yogurt': ('Iogurte', [448, 449, 451, 450, 452]),
	'yolk': ('Gema de ovo', [487]),
	'zucchini': ('Abobrinha', [70, 72, 71]),
	# Reconhecidos pela Apple, mas sem equivalente na TACO: o app avisa e oferece busca manual.
	'pizza': ('Pizza', []),
	'sushi': ('Sushi', []),
	'sandwich': ('Sanduíche', []),
	'ice_cream': ('Sorvete', []),
	'mushroom': ('Cogumelo', []),
	'donut': ('Donut', []),
	'pancake': ('Panqueca', []),
	'waffle': ('Waffle', []),
	'soup': ('Sopa', []),
	'hotdog': ('Cachorro-quente', []),
	'burrito': ('Burrito', []),
	'taco': ('Taco', []),
	'lasagna_unused': ('', []),
	'croissant': ('Croissant', []),
	'brownie': ('Brownie', []),
	'muffin': ('Muffin', []),
	'cupcake': ('Cupcake', []),
	'pie': ('Torta', []),
	'scrambled_eggs': ('Ovo mexido', []),
	'oatmeal': ('Mingau de aveia', []),
	'wine': ('Vinho', []),
	'red_wine': ('Vinho tinto', []),
	'white_wine': ('Vinho branco', []),
	'smoothie': ('Vitamina / smoothie', []),
	'milkshake': ('Milkshake', []),
	'cherry': ('Cereja', []),
	'blueberry': ('Mirtilo', []),
	'raspberry': ('Framboesa', []),
	'blackberry': ('Amora', []),
	'risotto': ('Risoto', []),
	'ramen': ('Lámen', []),
	'dumpling': ('Bolinho cozido (dumpling)', []),
	'quinoa': ('Quinoa', []),
	'asparagus': ('Aspargo', []),
	'nachos': ('Nachos', []),
	'pudding': ('Pudim', []),
	'water': ('Água', []),
}
LABELS.pop('lasagna_unused')

# Rótulos genéricos: indicam que há comida, mas não qual.
GENERIC = ['food', 'fruit', 'vegetable', 'dessert', 'drink', 'baked_goods', 'grain', 'meat_unused']
GENERIC.remove('meat_unused')

# Medidas caseiras preferidas como porção inicial (ordem de preferência).
PREFERRED_MEASURES = [
	'unidade', 'fatia', 'file', 'bife', 'pedaco', 'escumadeira', 'colher_de_arroz', 'concha',
	'colher_de_servir', 'copo', 'xicara', 'colher_de_sopa',
]


def num(v):
	"""TACO: número | {'trace': True} (Tr = traço) | None (não publicado)."""
	if isinstance(v, dict) and v.get('trace'):
		return 0.0
	return v


def main(raw_path: str, out_dir: str) -> None:
	raw = json.load(open(raw_path, encoding='utf8'))
	foods = raw['foods_default']['foods']
	by_id = {f['id']: f for f in foods}
	assert len(foods) == 597, len(foods)

	fa = raw['profiles_default']['tables']['fatty_acids']
	sat_idx = [c['key'] for c in fa['columns']].index('saturated_g')
	saturated = {row['id']: num(row['v'][sat_idx]) for row in fa['foods']}

	measures = {}
	for h in raw['household_default']['foods']:
		ms = [
			{'name': m['measure'], 'grams': m['grams'], 'key': m['key'], 'source': m['source_description']}
			for m in h['measures']
			if m['grams'] and m['grams'] > 0
		]
		ms.sort(key=lambda m: (PREFERRED_MEASURES.index(m['key']) if m['key'] in PREFERRED_MEASURES else 99))
		measures[h['taco_id']] = ms

	out_foods = []
	for f in foods:
		n = f['nutrients']
		item = {
			'id': f['id'],
			'name': f['name'].strip(),
			'category': f['category'],
			'kcal': num(n['energy_kcal']),
			'protein': num(n['protein_g']),
			'fat': num(n['lipids_g']),
			'carbs': num(n['carbohydrate_g']),
			'fiber': num(n['dietary_fiber_g']),
			'sodium': num(n['sodium_mg']),
			'saturated': saturated.get(f['id']),
			'measures': [{'name': m['name'], 'grams': m['grams'], 'source': m['source']} for m in measures.get(f['id'], [])],
		}
		out_foods.append(item)

	labels = []
	for label, (pt, ids) in sorted(LABELS.items()):
		for i in ids:
			assert i in by_id, (label, i)
		labels.append({'label': label, 'name': pt, 'foodIDs': ids})

	out = Path(out_dir)
	out.mkdir(parents=True, exist_ok=True)
	(out / 'taco.json').write_text(json.dumps(out_foods, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
	(out / 'labels.json').write_text(
		json.dumps({'labels': labels, 'generic': GENERIC}, ensure_ascii=False, separators=(',', ':')), encoding='utf8'
	)
	with_measures = sum(1 for f in out_foods if f['measures'])
	print(f'{len(out_foods)} alimentos, {with_measures} com medida caseira IBGE, {len(labels)} rótulos')
	for label, (pt, ids) in sorted(LABELS.items()):
		if ids:
			print(f'  {label:18} -> {by_id[ids[0]]["name"]}')


if __name__ == '__main__':
	main(sys.argv[1], sys.argv[2])
