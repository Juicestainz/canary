/**
 * Canary - A free and open-source MMORPG server emulator
 * Copyright (©) 2019–present OpenTibiaBR <opentibiabr@outlook.com>
 * Repository: https://github.com/opentibiabr/canary
 * License: https://github.com/opentibiabr/canary/blob/main/LICENSE
 * Contributors: https://github.com/opentibiabr/canary/graphs/contributors
 * Website: https://docs.opentibiabr.com/
 */

#pragma once

#include <exception>
#include <string>

#include "declarations.hpp"

class FileStream;
class Map;

class IOMap {
public:
	static void loadMap(Map* map, const Position &pos = Position());

	/**
	 * Load main map monsters
	 * \param map Is the map class
	 * \returns true if the monsters spawn map was loaded successfully
	 */
	static bool loadMonsters(Map* map);

	/**
	 * Load main map zones
	 * \param map Is the map class
	 * \returns true if the zones spawn map was loaded successfully
	 */
	static bool loadZones(Map* map);

	/**
	 * Load main map npcs
	 * \param map Is the map class
	 * \returns true if the npcs spawn map was loaded successfully
	 */
	static bool loadNpcs(Map* map);

	/**
	 * Load main map houses
	 * \param map Is the map class
	 * \returns true if the main map houses was loaded successfully
	 */
	static bool loadHouses(Map* map);

	/**
	 * Load custom  map monsters
	 * \param map Is the map class
	 * \returns true if the monsters spawn map custom was loaded successfully
	 */
	static bool loadMonstersCustom(Map* map, const std::string &mapName, int customMapIndex);

	/**
	 * Load custom  map zones
	 * \param map Is the map class
	 * \returns true if the zones spawn map custom was loaded successfully
	 */
	static bool loadZonesCustom(Map* map, const std::string &mapName, int customMapIndex);

	/**
	 * Load custom map npcs
	 * \param map Is the map class
	 * \returns true if the npcs spawn map custom was loaded successfully
	 */
	static bool loadNpcsCustom(Map* map, const std::string &mapName, int customMapIndex);

	/**
	 * Load custom map houses
	 * \param map Is the map class
	 * \returns true if the map custom houses was loaded successfully
	 */
	static bool loadHousesCustom(Map* map, const std::string &mapName, int customMapIndex);

private:
	static void parseMapDataAttributes(FileStream &stream, Map* map);
	static void parseWaypoints(FileStream &stream, Map &map);
	static void parseTowns(FileStream &stream, Map &map);
	static void parseTileArea(FileStream &stream, Map &map, const Position &pos);
};

class IOMapException : public std::exception {
public:
	explicit IOMapException(std::string msg) :
		message(std::move(msg)) { }

	const char* what() const noexcept override {
		return message.c_str();
	}

private:
	std::string message;
};
